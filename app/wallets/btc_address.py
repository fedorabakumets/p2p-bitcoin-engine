"""Mainnet Bitcoin address check. Accept bc1, 1, and 3. Reject everything else."""

import hashlib

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def is_btc_mainnet_address(address: str) -> bool:
    value = address.strip()
    if not value or any(char.isspace() for char in value):
        return False
    if value.lower().startswith("bc1"):
        return _is_bech32_mainnet(value)
    if value[0] in {"1", "3"}:
        return _is_base58_mainnet(value)
    return False


def normalize_btc_mainnet_address(address: str) -> str:
    value = address.strip()
    if not is_btc_mainnet_address(value):
        raise ValueError("invalid btc address")
    if value.lower().startswith("bc1"):
        return value.lower()
    return value


def _is_base58_mainnet(address: str) -> bool:
    if not 26 <= len(address) <= 35:
        return False
    raw = _b58decode(address)
    if raw is None or len(raw) != 25:
        return False
    version = raw[0]
    if address[0] == "1" and version != 0x00:
        return False
    if address[0] == "3" and version != 0x05:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    return digest[:4] == checksum


def _b58decode(text: str) -> bytes | None:
    number = 0
    for char in text:
        index = _BASE58_ALPHABET.find(char)
        if index < 0:
            return None
        number = number * 58 + index
    pad = 0
    for char in text:
        if char == "1":
            pad += 1
        else:
            break
    if number == 0:
        decoded = b""
    else:
        decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\x00" * pad + decoded


def _is_bech32_mainnet(address: str) -> bool:
    if any(char.islower() for char in address) and any(char.isupper() for char in address):
        return False
    address = address.lower()
    if not address.startswith("bc1") or len(address) > 90:
        return False
    separator = address.rfind("1")
    if separator < 1 or separator + 7 > len(address):
        return False
    hrp, data_part = address[:separator], address[separator + 1 :]
    if hrp != "bc":
        return False
    data: list[int] = []
    for char in data_part:
        index = _BECH32_CHARSET.find(char)
        if index < 0:
            return False
        data.append(index)
    spec = _verify_checksum(hrp, data)
    if spec is None or not data:
        return False
    version = data[0]
    if version > 16:
        return False
    if version == 0 and spec != "bech32":
        return False
    if version != 0 and spec != "bech32m":
        return False
    program = _convertbits(data[1:-6], 5, 8, pad=False)
    if program is None or not 2 <= len(program) <= 40:
        return False
    if version == 0 and len(program) not in (20, 32):
        return False
    return True


def _polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index in range(5):
            if (top >> index) & 1:
                checksum ^= generators[index]
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def _verify_checksum(hrp: str, data: list[int]) -> str | None:
    constant = _polymod(_hrp_expand(hrp) + data)
    if constant == _BECH32_CONST:
        return "bech32"
    if constant == _BECH32M_CONST:
        return "bech32m"
    return None


def _convertbits(data: list[int], from_bits: int, to_bits: int, *, pad: bool) -> list[int] | None:
    acc = 0
    bits = 0
    result: list[int] = []
    max_value = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            return None
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            result.append((acc >> bits) & max_value)
    if pad:
        if bits:
            result.append((acc << (to_bits - bits)) & max_value)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & max_value):
        return None
    return result
