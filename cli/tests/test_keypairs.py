"""Tests for st_cli.core.keypairs — pure-python Ed25519 and RSA key generation."""

from __future__ import annotations

import base64
import math
import secrets

import pytest

# A TEST dependency only (declared in the [dev] extra): the differential check
# below must never silently skip, so the import is hard — a missing lib fails
# collection loudly instead of quietly shrinking coverage.
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from st_cli.core import keypairs

# The autouse RSA stub of conftest.py skips tests marked `real_rsa`.
pytestmark = pytest.mark.real_rsa

# RFC 8032 §7.1 test vectors (TEST 1 / TEST 2 / TEST 3): secret seed → public key.
_RFC8032_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
    ),
]


def test_derive_public_key_matches_rfc8032_vectors():
    for seed_hex, pub_hex in _RFC8032_VECTORS:
        assert keypairs.derive_public_key(bytes.fromhex(seed_hex)).hex() == pub_hex


def test_generate_keypair_format_and_roundtrip():
    """Both halves are unpadded base64url of raw 32-byte values (the upstream
    new-issuer.py format), and the public half re-derives from the private seed."""
    private, public = keypairs.generate_keypair()
    for value in (private, public):
        assert len(value) == 43  # 32 bytes → 43 base64url chars, no padding
        assert "=" not in value
        raw = base64.urlsafe_b64decode(value + "=")
        assert len(raw) == 32
    seed = base64.urlsafe_b64decode(private + "=")
    assert keypairs.derive_public_key(seed) == base64.urlsafe_b64decode(public + "=")


def test_generate_keypair_is_random():
    assert keypairs.generate_keypair() != keypairs.generate_keypair()


def test_derive_public_key_matches_cryptography_lib():
    """Differential check against pyca/cryptography (a [dev]-extra test dep):
    random + edge seeds must derive byte-identical public keys."""
    seeds = [bytes(32), bytes([0xFF]) * 32]  # edge: all-zeros, all-ones
    # 25 random seeds ≈ 3 s (each pure-python derivation costs ~130 ms); a
    # systematic math error would fail on every seed anyway.
    seeds += [secrets.token_bytes(32) for _ in range(25)]
    for seed in seeds:
        ref = (
            Ed25519PrivateKey.from_private_bytes(seed)
            .public_key()
            .public_bytes(Encoding.Raw, PublicFormat.Raw)
        )
        assert keypairs.derive_public_key(seed) == ref, seed.hex()


@pytest.fixture(scope="module")
def rsa_pem():
    return keypairs.generate_rsa_private_key_pem()


def _load(pem):
    return load_pem_private_key(pem.encode("ascii"), password=None)


def test_rsa_pem_format(rsa_pem):
    lines = rsa_pem.split("\n")
    assert lines[0] == "-----BEGIN PRIVATE KEY-----"
    assert lines[-2] == "-----END PRIVATE KEY-----"
    assert lines[-1] == ""
    assert all(len(line) == 64 for line in lines[1:-3])
    assert 0 < len(lines[-3]) <= 64
    assert rsa_pem.endswith("-----\n") and not rsa_pem.endswith("\n\n")


def test_rsa_key_loads_with_expected_numbers(rsa_pem):
    key = _load(rsa_pem)
    nums = key.private_numbers()
    p, q = nums.p, nums.q
    assert key.key_size == 2048
    assert nums.public_numbers.e == 65537
    assert p > q
    d = pow(65537, -1, (p - 1) * (q - 1) // math.gcd(p - 1, q - 1))
    assert nums.d == d
    assert nums.dmp1 == d % (p - 1)
    assert nums.dmq1 == d % (q - 1)
    assert nums.iqmp == pow(q, -1, p)
    assert nums.public_numbers.n == p * q


def test_rsa_pem_is_byte_identical_to_cryptography(rsa_pem):
    out = _load(rsa_pem).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    assert out.decode("ascii") == rsa_pem


def test_rsa_encoder_matches_cryptography_on_its_primes():
    ref = rsa.generate_private_key(65537, 2048)
    nums = ref.private_numbers()
    p, q = max(nums.p, nums.q), min(nums.p, nums.q)
    # Rebuild the key from our ordering so the CRT values follow it.
    d = pow(65537, -1, math.lcm(p - 1, q - 1))
    rebuilt = rsa.RSAPrivateNumbers(
        p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p), nums.public_numbers
    ).private_key()
    want = rebuilt.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    assert keypairs._rsa_pkcs8_pem(p, q).encode("ascii") == want


def test_rsa_sign_and_verify_round_trip(rsa_pem):
    key = _load(rsa_pem)
    message = b"header.payload"
    signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    key.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())


def test_two_rsa_keys_differ(rsa_pem):
    assert keypairs.generate_rsa_private_key_pem() != rsa_pem


@pytest.mark.parametrize("bits", [1024, 2047, 2049])
def test_rsa_rejects_bad_size(bits):
    with pytest.raises(ValueError):
        keypairs.generate_rsa_private_key_pem(bits)


@pytest.mark.parametrize(
    "n", [2, 3, 5, 97, 1999, 2003, 7919, 2**31 - 1, 2**127 - 1, 2**521 - 1]
)
def test_is_probable_prime_accepts_primes(n):
    assert keypairs._is_probable_prime(n)


@pytest.mark.parametrize("n", [0, 1, 4, 9, 1999 * 2003, 2**127 - 3, 561, 41041, 825265])
def test_is_probable_prime_rejects_composites(n):
    assert not keypairs._is_probable_prime(n)


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, b"\x02\x01\x00"),
        (127, b"\x02\x01\x7f"),
        (128, b"\x02\x02\x00\x80"),
        (256, b"\x02\x02\x01\x00"),
    ],
)
def test_der_int_is_minimal(n, expected):
    assert keypairs._der_int(n) == expected


def test_der_long_length_form():
    assert keypairs._der(0x04, b"\0" * 5)[:2] == b"\x04\x05"
    assert keypairs._der(0x04, b"\0" * 300)[:4] == b"\x04\x82\x01\x2c"
