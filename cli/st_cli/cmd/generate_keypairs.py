"""``st-cli generate-keypairs APP ENV`` — mint JWT keys for file-scanner and docs.

For ``docs``, the command mints the two RSA private keys of La Suite Docs v6
(``JWT_PRIVATE_KEY`` for the backend, ``YHUB_JWT_PRIVATE_KEY`` for yhub) and
prints them with the steps to store them. It writes nothing.

For ``file-scanner``, two modes, both pure local keygen followed by a wiring summary:

* default — CLI twin of file-scanner's ``deploy/scripts/new-issuer.py``: a small
  questionnaire (issuer name per keypair, loop for several callers). For each
  caller it prints the ``iss:pubkey`` fragment to put in file-scanner's
  ``JWT_ISSUER_KEYS`` — merged with the value already present in the
  bootstrapped unit's env blob, if any — and the private key to hand to that
  caller (e.g. transfers uses it as ``SCAN_JWT_PRIVATE_KEY``).
* ``--signing-key`` — mint the seed file-scanner signs its outgoing webhooks
  with (``JWT_SIGNING_KEY``). ``bootstrap`` generates that one itself on the
  ansible-vault backend, so this mode is for the hashi_vault backend (which
  generates and writes nothing: the secret must pre-exist in OpenBao) and for
  rotating the key.

st-cli keeps NO copy of the private keys: they are displayed once. That is the
point — the private half belongs to a vault this command does not own (the
caller's own unit, or OpenBao).
"""

from __future__ import annotations

from ..core import appmeta, keypairs, manifest, paths, tree, ui
from ..core.errors import StCliError
from ..core.models import BACKEND_HASHI_VAULT
from ..core.prompts import _ask, _confirm

__all__ = ["generate"]


def _env_value(meta, env: str, key: str) -> str | None:
    """Current value of ``key`` in the bootstrapped unit's env blob.

    Returns ``None`` when the unit is not bootstrapped yet (the normal case:
    keys are minted BEFORE bootstrap, which prompts for them) or when the blob
    carries no such line.
    """
    core = meta.core()
    if not paths.vars_path(meta.app, env, core.key).exists():
        return None
    spec = meta.env_render_spec(core.key)
    blob_var = spec["backend"]["blob_var"]
    blob = tree.load_vars(meta.app, env, core.key).get(blob_var) or ""
    for line in blob.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or None
    return None


def _backend_kind(app: str, env: str) -> str:
    """Secret backend recorded for ``(app, env)``, ansible-vault by default.

    Best-effort: before the first bootstrap there is no ``.st-cli.yml`` at all,
    and the guidance below only needs to know which wording applies.
    """
    if not paths.manifest_path().exists():
        return "ansible-vault"
    return manifest.secret_config_for(manifest.load_manifest(), app, env).backend


def _generate_signing_key(meta, app: str, env: str) -> None:
    """Mint the webhook signing seed and print where it goes."""
    ui.info(f"Minting the webhook signing key for {app}/{env}.")
    private, public = keypairs.generate_keypair()
    core_key = meta.core().key
    bootstrapped = paths.vars_path(app, env, core_key).exists()
    hashi = _backend_kind(app, env) == BACKEND_HASHI_VAULT

    if hashi:
        target = "store it in OpenBao, then " + (
            f"point the JWT_SIGNING_KEY lookup in {app}/{env}/{core_key}/vars.yml "
            f"at it and `st-cli deploy {app} {env}`"
            if bootstrapped
            else f"give its lookup term when `st-cli bootstrap {app} {env}` "
            "asks for JWT_SIGNING_KEY"
        )
    elif bootstrapped:
        target = (
            f"set vault_jwt_signing_key to it with `st-cli secrets {app} {env}`, "
            f"then `st-cli deploy {app} {env}`"
        )
    else:
        target = (
            f"`st-cli bootstrap {app} {env}` generates one itself on this backend — "
            "use the key below only to override it"
        )

    kid = _env_value(meta, env, "JWT_SIGNING_KID")
    rotation = (
        f"Rotating: this unit advertises the current key under JWT_SIGNING_KID={kid} — "
        "give the new key a new label so receivers that cached the old one keep "
        "verifying in-flight webhooks.\n"
        if kid
        else ""
    )

    # Guidance in a panel; the actual values OUTSIDE it via ui.value — a Panel
    # would hard-fold long keys and break copy-paste.
    ui.note(
        f"[bold]{app} side[/bold]: JWT_SIGNING_KEY is the seed signing the outgoing "
        f"webhooks — {target}.\n"
        f"{rotation}"
        "[bold]receiver side[/bold]: nothing to hand over — receivers verify against "
        "the public half, which file-scanner advertises at /.well-known/jwks.json "
        "(printed below only so you can check what they will see).\n"
        "This command is purely [bold]local[/bold]: it only generates and prints — "
        "nothing is written to the repo, the vault or OpenBao, no network is "
        "involved, and st-cli keeps [bold]no copy[/bold] of the key (shown only "
        "once, below).",
        title="Signing key",
    )
    ui.info("JWT_SIGNING_KEY:")
    ui.value(private)
    ui.info("public half (advertised at /.well-known/jwks.json):")
    ui.value(public)


_DOCS_KEYS = [("JWT_PRIVATE_KEY", "docs"), ("YHUB_JWT_PRIVATE_KEY", "yhub")]


def _has_key_item(meta, app: str, env: str, key: str, unit: str) -> bool:
    spec = meta.secret_files_spec(unit)
    if not paths.vars_path(app, env, unit).exists():
        return False
    items = tree.load_vars(app, env, unit).get(spec["var"])
    return isinstance(items, list) and any(
        hasattr(i, "get") and i.get("env") == key for i in items
    )


def _docs_state(meta, app: str, env: str) -> tuple[bool, str]:
    """Return ``(both keys wired, command that wires the missing one)``.

    A v5 tree has the core ``vars.yml`` but no key item: only `st-cli upgrade`
    writes it. After the release, a core with its key but no yhub unit needs
    the yhub bootstrap.
    """
    core_ok = _has_key_item(meta, app, env, *_DOCS_KEYS[0])
    yhub_ok = _has_key_item(meta, app, env, *_DOCS_KEYS[1])
    if core_ok and yhub_ok:
        return True, ""
    if core_ok:
        return False, f"`st-cli bootstrap {app} {env} -c yhub`"
    if paths.vars_path(app, env, meta.core().key).exists():
        return False, "`st-cli upgrade`"
    return False, f"`st-cli bootstrap {app} {env}`"


def _generate_docs(meta, app: str, env: str) -> None:
    """Mint the two RSA keys of docs and print where each one goes."""
    ui.info(f"Minting the two RSA keys for {app}/{env}. This takes a few seconds.")
    pems = [keypairs.generate_rsa_private_key_pem() for _ in _DOCS_KEYS]
    hashi = _backend_kind(app, env) == BACKEND_HASHI_VAULT
    wired, replay = _docs_state(meta, app, env)

    if hashi:
        steps = "\n".join(
            f"- store the key {key} in OpenBao (unit {unit}); "
            f"the default lookup term is `@openbao(kv/data/{app}:{key})`"
            for key, unit in _DOCS_KEYS
        )
        if wired:
            steps += (
                "\nThe units already hold these lookup terms. "
                "Replace the value in OpenBao at the path of each term, "
                f"then run `st-cli deploy {app} {env}`."
            )
        else:
            steps += (
                f"\nThen run {replay}. It asks for one lookup term per key. "
                "Give the term of the key you stored. Do not deploy before."
            )
    elif wired:
        commands = "\n".join(
            f"- `st-cli secrets {app} {env} -c {unit}`" for _, unit in _DOCS_KEYS
        )
        steps = (
            "Paste each YAML block below over the same variable in the vault "
            f"of its unit:\n{commands}\n"
            f"Then run `st-cli deploy {app} {env}`."
        )
    else:
        steps = (
            f"{replay} generates the missing key itself on this backend. "
            "Use the blocks below only to replace a key after that."
        )

    ui.note(
        f"[bold]docs[/bold]: JWT_PRIVATE_KEY signs the tokens of the backend. "
        f"[bold]yhub[/bold]: YHUB_JWT_PRIVATE_KEY signs the tokens of the "
        f"collaboration server.\n{steps}\n"
        "Rotation: each side reads the JWKS of the other side, so you can "
        "replace one key alone. You must restart the unit after the change.\n"
        "This command is purely [bold]local[/bold]: it only generates and prints. "
        "It writes nothing, and st-cli keeps [bold]no copy[/bold] of the keys "
        "(shown only once, below).",
        title="RSA keys",
    )
    for (key, unit), pem in zip(_DOCS_KEYS, pems, strict=True):
        ui.info(f"{key} (unit {unit}):")
        if hashi:
            ui.value(pem.rstrip("\n"))
        else:
            ui.value(_vault_block("vault_" + key.lower(), pem))


def _vault_block(name: str, pem: str) -> str:
    lines = "\n".join("  " + line for line in pem.splitlines())
    return f"{name}: |\n{lines}"


def generate(app: str, env: str, signing_key: bool = False) -> None:
    """Run the keypair questionnaire for ``(app, env)`` and print the summary.

    With ``signing_key``, mint the webhook signing seed instead (no
    questionnaire — that key has no issuer). For ``docs``, mint the two RSA keys.
    """
    meta = appmeta.load_app(app)  # unknown app → clean StCliError with the list
    if app == "docs":
        if signing_key:
            raise StCliError("--signing-key works only with file-scanner.")
        _generate_docs(meta, app, env)
        return
    if app != "file-scanner":
        raise StCliError(
            "generate-keypairs supports only file-scanner (Ed25519 keypairs) "
            "and docs (RSA keys)."
        )

    if signing_key:
        _generate_signing_key(meta, app, env)
        return

    ui.info(f"Minting caller keypair(s) for {app}/{env}.")
    pairs: list[tuple[str, str, str]] = []  # (iss, private, public)
    while True:
        iss = _ask("Issuer name (the calling app's `iss` claim)", "transfers")
        if ":" in iss or "," in iss:
            # ':' and ',' are the JWT_ISSUER_KEYS delimiters — re-prompt.
            ui.warn("Issuer name must not contain ':' or ','.")
            continue
        if any(p[0] == iss for p in pairs):
            ui.warn(f"Issuer {iss!r} already minted in this run — pick another name.")
            continue
        private, public = keypairs.generate_keypair()
        pairs.append((iss, private, public))
        ui.success(f"{iss}: keypair generated.")
        if not _confirm("Generate another caller keypair?", default=False):
            break

    existing = _env_value(meta, env, "JWT_ISSUER_KEYS")
    fragments = [f"{iss}:{public}" for iss, _, public in pairs]
    merged = ",".join(([existing] if existing else []) + fragments)

    core_key = meta.core().key
    if existing is not None:
        target = (
            f"update JWT_ISSUER_KEYS in {app}/{env}/{core_key}/vars.yml "
            f"(existing keys kept), then `st-cli deploy {app} {env}`"
        )
    elif paths.vars_path(app, env, core_key).exists():
        target = (
            f"add a JWT_ISSUER_KEYS line to {app}/{env}/{core_key}/vars.yml, "
            f"then `st-cli deploy {app} {env}`"
        )
    else:
        target = f"paste when `st-cli bootstrap {app} {env}` asks for JWT_ISSUER_KEYS"

    # Guidance in a panel; the actual values OUTSIDE it via ui.value — a Panel
    # would hard-fold long keys and break copy-paste.
    ui.note(
        f"[bold]{app} side[/bold]: set JWT_ISSUER_KEYS to the value below — {target}.\n"
        "JWT_ISSUER_KEYS is comma-separated: to add a caller to an already-set "
        "value, append `,iss:pubkey` to it.\n"
        "[bold]caller side[/bold]: hand each private key to its app over a secure "
        "channel (transfers uses SCAN_JWT_PRIVATE_KEY).\n"
        "This command is purely [bold]local[/bold]: it only generates and prints — "
        "nothing is written to the repo or the vault, no network is involved, and "
        "st-cli keeps [bold]no copy[/bold] of the private keys (shown only once, "
        "below).",
        title="Keypairs",
    )
    ui.info("JWT_ISSUER_KEYS:")
    ui.value(merged)
    for iss, private, _ in pairs:
        ui.info(f"{iss} private key:")
        ui.value(private)
