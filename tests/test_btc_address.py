from app.bot.client.amount import parse_rub_to_kop
from app.wallets.btc_address import is_btc_mainnet_address, normalize_btc_mainnet_address

BC1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
TAPROOT = "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kt5nd6y"
P2PKH = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
P2SH = "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64"


def test_accepts_mainnet_addresses() -> None:
    assert is_btc_mainnet_address(BC1)
    assert is_btc_mainnet_address(BC1.upper())
    assert is_btc_mainnet_address(TAPROOT)
    assert is_btc_mainnet_address(P2PKH)
    assert is_btc_mainnet_address(P2SH)
    assert normalize_btc_mainnet_address("  " + BC1.upper() + " ") == BC1
    assert normalize_btc_mainnet_address(P2PKH) == P2PKH


def test_rejects_junk() -> None:
    for value in (
        "",
        "hello",
        "bc1",
        "1",
        "3",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",
        "Bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",
        "3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy",
        "2N4FQj7n4Z4i5i6j7k8L9m0N",
    ):
        assert is_btc_mainnet_address(value) is False


def test_amount_parser() -> None:
    assert parse_rub_to_kop("2000") == 200_000
    assert parse_rub_to_kop("2 000 руб") == 200_000
    assert parse_rub_to_kop("2000,50") == 200_050
    for bad in ("0", "-5", "abc", "2000.555", ""):
        try:
            parse_rub_to_kop(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
