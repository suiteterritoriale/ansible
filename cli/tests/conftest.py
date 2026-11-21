"""Shared pytest fixtures for st-cli tests.

Autouse fixtures disable the global upstream-version check and replace the RSA
generator with fixed keys.
"""

from __future__ import annotations

import itertools

import pytest


@pytest.fixture(scope="session")
def _fixed_rsa_pems() -> tuple[str, str]:
    """Two PKCS#8 PEM keys, generated once per session for speed."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    def pem() -> str:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    return pem(), pem()


@pytest.fixture(autouse=True)
def _stub_rsa_generator(request, monkeypatch, _fixed_rsa_pems):
    """Cycle two fixed PEMs, so the two docs keys differ and a test stays fast.

    A module marked `real_rsa` keeps the real generator.
    """
    if request.node.get_closest_marker("real_rsa"):
        return
    from st_cli.core import keypairs

    cycle = itertools.cycle(_fixed_rsa_pems)
    monkeypatch.setattr(
        keypairs, "generate_rsa_private_key_pem", lambda bits=2048: next(cycle)
    )


@pytest.fixture(autouse=True)
def _disable_upstream_check(monkeypatch):
    monkeypatch.setenv("ST_CLI_NO_UPSTREAM_CHECK", "1")


@pytest.fixture(autouse=True)
def _disable_ssh_user_guard(monkeypatch):
    """Disable the ssh-user guard by default so no test makes a real ssh -G call."""
    from st_cli.core import sshuser

    monkeypatch.setattr(sshuser, "_checked", True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway deployment repo as the working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
