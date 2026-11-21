"""Tests for st_cli.cmd.generate_keypairs — the caller-keypair questionnaire.

The summary is asserted by capturing the ui calls (note body + raw values)
rather than parsing rendered rich output: long single-word keys get folded by
the terminal renderer, which would make text-matching brittle.
"""

from __future__ import annotations

import base64
import re

import pytest
from helpers import script_questionary

from st_cli.cmd import generate_keypairs
from st_cli.core import keypairs, manifest, tree
from st_cli.core.errors import StCliError
from st_cli.core.models import SecretConfig, StCliManifest


def _capture_ui(monkeypatch):
    """Capture ui.note bodies, ui.value lines and ui.warn lines."""
    notes: list[str] = []
    values: list[str] = []
    warns: list[str] = []
    monkeypatch.setattr(
        generate_keypairs.ui, "note", lambda body, title="Note": notes.append(body)
    )
    monkeypatch.setattr(generate_keypairs.ui, "value", values.append)
    monkeypatch.setattr(generate_keypairs.ui, "warn", warns.append)
    return notes, values, warns


def test_generate_single_keypair_summary(repo, monkeypatch):
    """Default flow: one keypair for issuer `transfers`, no bootstrapped unit →
    the guidance points at the bootstrap questionnaire and the printed halves
    form a consistent Ed25519 pair."""
    notes, values, _ = _capture_ui(monkeypatch)
    script_questionary(
        monkeypatch,
        [
            ("text", "Issuer name", "transfers"),
            ("confirm", "another caller keypair", False),
        ],
    )
    generate_keypairs.generate("file-scanner", "prod")

    guidance = notes[0]
    assert "JWT_ISSUER_KEYS" in guidance
    assert "st-cli bootstrap file-scanner prod" in guidance
    assert "SCAN_JWT_PRIVATE_KEY" in guidance
    assert "no copy" in guidance
    # how to append to an already-set value, and the purely-local promise
    assert "append `,iss:pubkey`" in guidance
    assert "nothing is written" in guidance

    merged, private = values
    pub = re.fullmatch(r"transfers:([A-Za-z0-9_-]{43})", merged).group(1)
    seed = base64.urlsafe_b64decode(private + "=")
    assert keypairs.derive_public_key(seed) == base64.urlsafe_b64decode(pub + "=")


def test_generate_multiple_and_invalid_issuer_reprompts(repo, monkeypatch):
    """A ':'/',' issuer name or a duplicate warns + re-prompts without minting;
    the loop then mints two keypairs and joins both fragments with a comma."""
    _, values, warns = _capture_ui(monkeypatch)
    script_questionary(
        monkeypatch,
        [
            ("text", "Issuer name", "bad:name"),
            ("text", "Issuer name", "transfers"),
            ("confirm", "another caller keypair", True),
            ("text", "Issuer name", "transfers"),  # duplicate → re-prompt
            ("text", "Issuer name", "drive"),
            ("confirm", "another caller keypair", False),
        ],
    )
    generate_keypairs.generate("file-scanner", "prod")

    assert len(warns) == 2  # invalid name + duplicate
    merged = values[0]
    assert re.fullmatch(r"transfers:[A-Za-z0-9_-]{43},drive:[A-Za-z0-9_-]{43}", merged)
    assert len(values) == 3  # merged + one private key per issuer


def test_generate_merges_existing_issuer_keys(repo, monkeypatch):
    """With a bootstrapped file-scanner unit whose env blob already carries
    JWT_ISSUER_KEYS, the new fragment is appended after the existing value and
    the guidance points at vars.yml + deploy instead of bootstrap."""
    data = tree.load_vars("file-scanner", "prod", "file-scanner")
    data["st_file_scanner_env"] = "JWT_ISSUER_KEYS=old:oldpubkey\nJWT_SIGNING_KID=v1\n"
    tree.save_vars("file-scanner", "prod", "file-scanner", data)
    notes, values, _ = _capture_ui(monkeypatch)
    script_questionary(
        monkeypatch,
        [
            ("text", "Issuer name", "drive"),
            ("confirm", "another caller keypair", False),
        ],
    )
    generate_keypairs.generate("file-scanner", "prod")

    assert re.fullmatch(r"old:oldpubkey,drive:[A-Za-z0-9_-]{43}", values[0])
    guidance = notes[0]
    assert "file-scanner/prod/file-scanner/vars.yml" in guidance
    assert "st-cli deploy file-scanner prod" in guidance
    assert "st-cli bootstrap" not in guidance


def test_signing_key_not_bootstrapped(repo, monkeypatch):
    """--signing-key mints one seed with no questionnaire; before bootstrap the
    guidance says bootstrap generates it on the ansible-vault backend, and both
    printed halves form a consistent Ed25519 pair."""
    notes, values, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("file-scanner", "prod", signing_key=True)

    guidance = notes[0]
    assert "JWT_SIGNING_KEY" in guidance
    assert "st-cli bootstrap file-scanner prod` generates one itself" in guidance
    assert "/.well-known/jwks.json" in guidance
    assert "no copy" in guidance
    assert "Rotating" not in guidance  # no JWT_SIGNING_KID to rotate away from

    private, public = values
    seed = base64.urlsafe_b64decode(private + "=")
    assert keypairs.derive_public_key(seed) == base64.urlsafe_b64decode(public + "=")


def test_signing_key_bootstrapped_ansible_vault_mentions_rotation(repo, monkeypatch):
    """With a bootstrapped unit on the default backend, the guidance routes the
    seed through `st-cli secrets` + deploy and warns to relabel JWT_SIGNING_KID."""
    data = tree.load_vars("file-scanner", "prod", "file-scanner")
    data["st_file_scanner_env"] = (
        "JWT_SIGNING_KEY={{ vault_jwt_signing_key }}\nJWT_SIGNING_KID=v1\n"
    )
    tree.save_vars("file-scanner", "prod", "file-scanner", data)
    notes, values, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("file-scanner", "prod", signing_key=True)

    guidance = notes[0]
    assert "st-cli secrets file-scanner prod" in guidance
    assert "vault_jwt_signing_key" in guidance
    assert "JWT_SIGNING_KID=v1" in guidance
    # OpenBao is only named by the "nothing is written" promise, not as a target
    assert "store it in OpenBao" not in guidance
    assert len(values) == 2  # seed + public half


def test_signing_key_hashi_vault_points_at_openbao(repo, monkeypatch):
    """On the hashi_vault backend the guidance says to store the seed in OpenBao
    and point the lookup at it — never to write a vault.yml."""
    manifest.save_manifest(
        StCliManifest(
            "0.0.19",
            "0.0.19",
            [],
            [SecretConfig("file-scanner", "prod", "hashi_vault")],
        )
    )
    notes, _, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("file-scanner", "prod", signing_key=True)

    guidance = notes[0]
    assert "store it in OpenBao" in guidance
    assert "asks for JWT_SIGNING_KEY" in guidance
    assert "st-cli secrets" not in guidance


def test_generate_rejects_other_apps(repo, monkeypatch):
    """Only file-scanner authenticates callers by keypair; other apps raise a
    clean StCliError (unknown apps too, via load_app)."""
    with pytest.raises(StCliError, match="only file-scanner"):
        generate_keypairs.generate("drive", "prod")
    with pytest.raises(StCliError, match="unknown app"):
        generate_keypairs.generate("bogus", "prod")


_FAKE_PEM = "-----BEGIN PRIVATE KEY-----\nAAAA\nBBBB\n-----END PRIVATE KEY-----\n"


@pytest.fixture
def fake_rsa(monkeypatch):
    monkeypatch.setattr(
        keypairs, "generate_rsa_private_key_pem", lambda bits=2048: _FAKE_PEM
    )


def test_docs_ansible_vault_prints_yaml_blocks(repo, monkeypatch, fake_rsa):
    notes, values, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert "`st-cli bootstrap docs prod` generates the missing key itself" in guidance
    assert "st-cli deploy" not in guidance
    assert "replace one key alone" in guidance
    assert "restart" in guidance
    assert "OpenBao" not in guidance
    assert values == [
        "vault_jwt_private_key: |\n"
        "  -----BEGIN PRIVATE KEY-----\n  AAAA\n  BBBB\n  -----END PRIVATE KEY-----",
        "vault_yhub_jwt_private_key: |\n"
        "  -----BEGIN PRIVATE KEY-----\n  AAAA\n  BBBB\n  -----END PRIVATE KEY-----",
    ]


def test_docs_hashi_vault_prints_raw_pem(repo, monkeypatch, fake_rsa):
    manifest.save_manifest(
        StCliManifest(
            "0.0.19", "0.0.19", [], [SecretConfig("docs", "prod", "hashi_vault")]
        )
    )
    notes, values, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert "@openbao(kv/data/docs:JWT_PRIVATE_KEY)" in guidance
    assert "@openbao(kv/data/docs:YHUB_JWT_PRIVATE_KEY)" in guidance
    assert "unit docs" in guidance and "unit yhub" in guidance
    assert "Then run `st-cli bootstrap docs prod`." in guidance
    assert "one lookup term per key" in guidance
    assert "st-cli deploy" not in guidance.replace("Do not deploy", "")
    assert "st-cli secrets" not in guidance
    assert values == [_FAKE_PEM.rstrip("\n")] * 2


def test_docs_writes_nothing(repo, monkeypatch, fake_rsa):
    _capture_ui(monkeypatch)
    before = sorted(p.name for p in repo.iterdir())
    generate_keypairs.generate("docs", "prod")
    assert sorted(p.name for p in repo.iterdir()) == before


def test_docs_rejects_signing_key(repo, monkeypatch, fake_rsa):
    with pytest.raises(StCliError, match="only with file-scanner"):
        generate_keypairs.generate("docs", "prod", signing_key=True)


def _save_docs_units(*, core_item: bool, yhub_item: bool) -> None:
    core = {"st_docs_backend_secret_files": []}
    if core_item:
        core["st_docs_backend_secret_files"].append(
            {"env": "JWT_PRIVATE_KEY", "content": "{{ x }}"}
        )
    tree.save_vars("docs", "prod", "docs", core)
    if yhub_item is not None:
        yhub = {"st_docs_yhub_secret_files": []}
        if yhub_item:
            yhub["st_docs_yhub_secret_files"].append(
                {"env": "YHUB_JWT_PRIVATE_KEY", "content": "{{ y }}"}
            )
        tree.save_vars("docs", "prod", "yhub", yhub)


def _hashi_manifest() -> None:
    manifest.save_manifest(
        StCliManifest(
            "0.0.19", "0.0.19", [], [SecretConfig("docs", "prod", "hashi_vault")]
        )
    )


def test_docs_hashi_vault_wired_units_point_at_openbao_value(
    repo, monkeypatch, fake_rsa
):
    """Both units list their key: replace the value in OpenBao, then deploy."""
    _hashi_manifest()
    _save_docs_units(core_item=True, yhub_item=True)
    notes, _, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert "The units already hold these lookup terms" in guidance
    assert "then run `st-cli deploy docs prod`" in guidance
    assert "st-cli bootstrap" not in guidance


@pytest.mark.parametrize(
    "core_item,yhub_item,command",
    [
        (False, None, "`st-cli upgrade`"),  # a v5 tree
        (False, True, "`st-cli upgrade`"),
        (True, None, "`st-cli bootstrap docs prod -c yhub`"),  # core wired, no yhub
        (True, False, "`st-cli bootstrap docs prod -c yhub`"),
    ],
)
def test_docs_hashi_vault_unwired_tree_names_the_right_command(
    repo, monkeypatch, fake_rsa, core_item, yhub_item, command
):
    """A v5 tree (or a half-wired one) lacks a key item: only a replay or the
    yhub bootstrap writes it, so the text names that command, never deploy."""
    _hashi_manifest()
    _save_docs_units(core_item=core_item, yhub_item=yhub_item)
    notes, _, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert f"Then run {command}." in guidance
    assert "already hold" not in guidance
    assert "then run `st-cli deploy" not in guidance
    assert "Do not deploy before" in guidance


def test_docs_ansible_vault_wired_units_paste_then_deploy(repo, monkeypatch, fake_rsa):
    _save_docs_units(core_item=True, yhub_item=True)
    notes, _, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert "st-cli secrets docs prod -c docs" in guidance
    assert "st-cli secrets docs prod -c yhub" in guidance
    assert "then run `st-cli deploy docs prod`" in guidance.replace("Then", "then")


def test_docs_ansible_vault_v5_tree_points_at_upgrade(repo, monkeypatch, fake_rsa):
    _save_docs_units(core_item=False, yhub_item=None)
    notes, _, _ = _capture_ui(monkeypatch)
    generate_keypairs.generate("docs", "prod")

    guidance = notes[0]
    assert "`st-cli upgrade` generates the missing key itself" in guidance
    assert "st-cli deploy" not in guidance
