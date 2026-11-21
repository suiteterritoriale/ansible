"""Key generation for the JWT auth of file-scanner (Ed25519) and docs (RSA).

st-cli deliberately carries no crypto dependency, and the only primitive the
``generate-keypairs`` command needs is deriving an Ed25519 public key from a
32-byte seed — so the RFC 8032 reference math is inlined below. Keygen only:
no signing, no verification, no untrusted input, and side-channel resistance
is irrelevant for a local one-shot mint. Correctness is pinned to the RFC 8032
test vectors in ``tests/test_keypairs.py``.

Output format matches upstream file-scanner exactly (its ``jwt_auth`` parser
and ``deploy/scripts/new-issuer.py``): the raw 32-byte values as unpadded
URL-safe base64 — the private key IS the seed.
"""

from __future__ import annotations

import base64
import hashlib
import math
import secrets

_P = 2**255 - 19


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * _inv(5) % _P
_B = (_xrecover(_BY), _BY)


def _edwards_add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _D * x1 * x2 * y1 * y2)
    return x3 % _P, y3 % _P


def _scalarmult_base(e: int) -> tuple[int, int]:
    p, q = _B, (0, 1)  # (0, 1) is the neutral element
    while e:
        if e & 1:
            q = _edwards_add(q, p)
        p = _edwards_add(p, p)
        e >>= 1
    return q


def derive_public_key(seed: bytes) -> bytes:
    """RFC 8032 §5.1.5: 32-byte Ed25519 seed → 32-byte compressed public key."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8  # clamp: clear the low 3 bits...
    a |= 1 << 254  # ...and set bit 254
    x, y = _scalarmult_base(a)
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_keypair() -> tuple[str, str]:
    """Mint a fresh keypair → ``(private_b64url, public_b64url)``."""
    seed = secrets.token_bytes(32)
    return _b64url(seed), _b64url(derive_public_key(seed))


_RSA_E = 65537
_SMALL_PRIMES = [
    n for n in range(3, 2000, 2) if all(n % d for d in range(3, int(n**0.5) + 1, 2))
]


def _is_probable_prime(n: int, rounds: int = 40) -> bool:
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for sp in _SMALL_PRIMES:
        if n == sp:
            return True
        if n % sp == 0:
            return False
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rounds):
        x = pow(2 + secrets.randbelow(n - 3), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _rsa_prime(bits: int) -> int:
    while True:
        # Top two bits set: the product of two primes has exactly 2 * bits bits.
        c = secrets.randbits(bits) | (3 << (bits - 2)) | 1
        if math.gcd(c - 1, _RSA_E) == 1 and _is_probable_prime(c):
            return c


def _der(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + body


def _der_int(n: int) -> bytes:
    return _der(0x02, n.to_bytes(n.bit_length() // 8 + 1, "big"))


def _rsa_pkcs8_pem(p: int, q: int) -> str:
    """Encode the RSA key of the primes ``p > q`` as an unencrypted PKCS#8 PEM."""
    d = pow(_RSA_E, -1, math.lcm(p - 1, q - 1))
    numbers = [0, p * q, _RSA_E, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p)]
    pkcs1 = _der(0x30, b"".join(_der_int(n) for n in numbers))
    algorithm = _der(0x30, bytes.fromhex("06092a864886f70d0101010500"))
    pkcs8 = _der(0x30, _der_int(0) + algorithm + _der(0x04, pkcs1))
    b64 = base64.b64encode(pkcs8).decode("ascii")
    lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
    return "\n".join(
        ["-----BEGIN PRIVATE KEY-----", *lines, "-----END PRIVATE KEY-----", ""]
    )


def generate_rsa_private_key_pem(bits: int = 2048) -> str:
    """Mint an RSA key (e = 65537) → unencrypted PKCS#8 PEM string."""
    if bits < 2048 or bits % 2:
        raise ValueError("RSA key size must be at least 2048 bits and even.")
    half = bits // 2
    while True:
        p, q = _rsa_prime(half), _rsa_prime(half)
        # FIPS 186-4: p and q must differ in their top 100 bits.
        if abs(p - q) >> (half - 100):
            return _rsa_pkcs8_pem(max(p, q), min(p, q))
