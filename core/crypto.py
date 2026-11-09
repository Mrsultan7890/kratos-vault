import os
import json
import struct
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import hashlib


PBKDF2_ITERATIONS = 600_000
MIN_PBKDF2_ITERATIONS = 100_000
MAX_PBKDF2_ITERATIONS = 1_200_000
MAX_ENCRYPTED_FILE_BYTES = 512 * 1024 * 1024
_STATUS_MAGIC = b"KVSTAT01"


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode())


def encrypt(data: dict, password: str) -> bytes:
    if len(password) < 12:
        raise ValueError("Encryption passwords must contain at least 12 characters")
    salt = os.urandom(32)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    plaintext = json.dumps(data, ensure_ascii=False).encode()
    if len(plaintext) + 68 > MAX_ENCRYPTED_FILE_BYTES:
        raise ValueError("Encrypted exports are limited to 512 MiB")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    # Format: magic(4) + iterations(4) + salt(32) + nonce(12) + ciphertext
    magic = b"KV20"
    header = struct.pack(">I", PBKDF2_ITERATIONS)
    return magic + header + salt + nonce + ciphertext


def decrypt(raw: bytes, password: str) -> dict:
    if len(raw) < 68 or len(raw) > MAX_ENCRYPTED_FILE_BYTES or raw[:4] != b"KV20":
        raise ValueError("Invalid file format or corrupted data")
    iterations = struct.unpack(">I", raw[4:8])[0]
    if not MIN_PBKDF2_ITERATIONS <= iterations <= MAX_PBKDF2_ITERATIONS:
        raise ValueError("Unsupported or unsafe key-derivation work factor")
    salt = raw[8:40]
    nonce = raw[40:52]
    ciphertext = raw[52:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = kdf.derive(password.encode())
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("Decryption failed — wrong password or corrupted file") from exc
    try:
        data = json.loads(plaintext.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Decrypted file does not contain valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Decrypted file must contain a JSON object")
    return data


def derive_status_key(password: str) -> bytes:
    return _derive_key(password, b"KratosVault status file v1")


def encrypt_status(data: dict, key: bytes) -> bytes:
    nonce = os.urandom(12)
    plaintext = json.dumps(data, ensure_ascii=False).encode()
    return _STATUS_MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, _STATUS_MAGIC)


def decrypt_status(raw: bytes, key: bytes) -> dict:
    if len(raw) < len(_STATUS_MAGIC) + 12 + 16 or raw[:len(_STATUS_MAGIC)] != _STATUS_MAGIC:
        raise ValueError("Invalid encrypted enrichment status file")
    offset = len(_STATUS_MAGIC)
    nonce = raw[offset:offset + 12]
    try:
        plaintext = AESGCM(key).decrypt(nonce, raw[offset + 12:], _STATUS_MAGIC)
        data = json.loads(plaintext.decode())
    except Exception as exc:
        raise ValueError("Enrichment status file authentication failed") from exc
    if not isinstance(data, dict):
        raise ValueError("Enrichment status file must contain an object")
    return data


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
