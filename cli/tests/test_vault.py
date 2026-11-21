"""Tests for st_cli.core.vault — ansible-vault wrappers + vault-password path
resolver."""

from __future__ import annotations

from helpers import file_mode

from st_cli.core import paths, tree, vault, writer
from st_cli.core.secretbackend import SecretBackend


def test_vault_file_roundtrip(repo):
    (repo / ".vault-pass").write_text("testpass\n")
    p = paths.vault_path("meet", "prod", "meet")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        tree.yaml().dump(
            {"vault_django_secret_key": "s3cr3t", "st_meet_livekit_api_secret": "abc"},
            fh,
        )
    vault.encrypt_file(p)

    assert vault.is_encrypted(p)
    assert p.read_text().startswith("$ANSIBLE_VAULT")
    back = vault.decrypt_to_dict(p)
    assert back["vault_django_secret_key"] == "s3cr3t"
    assert back["st_meet_livekit_api_secret"] == "abc"


def test_decrypt_to_dict_keeps_values_that_contain_the_vault_password(repo):
    """ansible-core 2.22 masks the vault password in `view` output: decrypt_to_dict
    must return the true values and leave the file untouched."""
    (repo / ".vault-pass").write_text("hunter2pass\n")
    values = {"a": "hunter2pass", "b": "xxhunter2passyy", "c": "other"}
    p = paths.vault_path("meet", "prod", "meet")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        tree.yaml().dump(values, fh)
    vault.encrypt_file(p)
    before = p.read_bytes()

    back = vault.decrypt_to_dict(p)

    assert back == values
    assert all("$REDACTED$" not in v for v in back.values())
    assert vault.is_encrypted(p)
    assert p.read_bytes() == before

    class _NewKeyBackend(SecretBackend):
        def component_secrets(self, component):
            return {"d": "new"}

    writer.write_vault("meet", "prod", "meet", _NewKeyBackend())

    assert vault.decrypt_to_dict(p) == {**values, "d": "new"}


def test_vault_password_path_default_is_repo_root(repo):
    """The resolver always returns the repo-root ``.vault-pass``."""
    assert vault.vault_password_path() == (repo / ".vault-pass")


def test_ensure_vault_password_generated_file_is_0600(repo):
    """A freshly generated `.vault-pass` is created at 0600, so it is never
    world-readable."""
    pw_path = paths.repo_root() / ".vault-pass"
    assert not pw_path.exists()

    vault.ensure_vault_password(create=True)

    assert pw_path.exists()
    assert file_mode(pw_path) == 0o600


def test_ensure_vault_password_normalises_loose_perms(repo):
    """An existing `.vault-pass` copied in at 0644 is repaired to 0600 on every
    ensure_vault_password call."""
    pw_path = paths.repo_root() / ".vault-pass"
    pw_path.write_text("testpass\n", encoding="utf-8")
    pw_path.chmod(0o644)  # simulate a file copied in under a loose umask
    assert file_mode(pw_path) == 0o644

    vault.ensure_vault_password(create=False)

    assert file_mode(pw_path) == 0o600
    assert pw_path.read_text(encoding="utf-8") == "testpass\n"  # content preserved
