from app.bot.client.amount import parse_rub_to_kop
from app.bot.client.texts import (
    ADDRESS_CHECKSUM_HINT,
    ADDRESS_PREFIX_HINT,
    ADDRESS_PREFIX_HINT_TESTNET,
    address_prompt,
    address_retry_text,
)
from app.wallets.btc_address import (
    classify_btc_address,
    classify_btc_mainnet_address,
    is_btc_address_for_network,
    is_btc_mainnet_address,
    is_btc_testnet_address,
    normalize_btc_address,
    normalize_btc_mainnet_address,
)

BC1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
BC1_P2WSH = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
BC1_EXAMPLE = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
BC1_TRUNCATED = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf"
TAPROOT = "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kt5nd6y"
P2PKH = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
P2SH = "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64"
TB1 = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
TB1_P2WSH = "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"
TB1_WRONG_CHECKSUM = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
TESTNET_P2PKH_M = "mpXwg4jMtRhuSpVq4xS3HFHmCmWp9NyGKt"
TESTNET_P2PKH_N = "n1YvL1N13wRXRdBTCXGGJDp8ayok3wcQD1"
TESTNET_P2SH = "2N2GDNJ4rEm6NxfMC9ck8VuRdheQzXWaNZv"


def test_accepts_mainnet_addresses() -> None:
    assert is_btc_mainnet_address(BC1)
    assert is_btc_mainnet_address(BC1.upper())
    assert is_btc_mainnet_address(BC1_P2WSH)
    assert is_btc_mainnet_address(BC1_EXAMPLE)
    assert is_btc_mainnet_address(TAPROOT)
    assert is_btc_mainnet_address(P2PKH)
    assert is_btc_mainnet_address(P2SH)
    assert normalize_btc_mainnet_address("  " + BC1.upper() + " ") == BC1
    assert normalize_btc_mainnet_address(BC1_EXAMPLE) == BC1_EXAMPLE
    assert normalize_btc_mainnet_address(P2PKH) == P2PKH
    assert classify_btc_mainnet_address(BC1_EXAMPLE) == "ok"
    assert classify_btc_mainnet_address(P2PKH) == "ok"
    assert classify_btc_mainnet_address(P2SH) == "ok"
    assert classify_btc_mainnet_address(TAPROOT) == "ok"


def test_testnet_addresses_are_accepted_only_on_testnet() -> None:
    for value in (TB1, TB1.upper(), TB1_P2WSH, TESTNET_P2PKH_M, TESTNET_P2PKH_N, TESTNET_P2SH):
        assert is_btc_testnet_address(value)
        assert is_btc_address_for_network(value, "testnet")
        assert is_btc_address_for_network(value, "mainnet") is False
        assert classify_btc_address(value, "testnet") == "ok"
        assert classify_btc_address(value, "mainnet") == "prefix"
    assert normalize_btc_address("  " + TB1.upper() + " ", "testnet") == TB1
    assert normalize_btc_address(TESTNET_P2PKH_M, "testnet") == TESTNET_P2PKH_M
    assert normalize_btc_address(TESTNET_P2SH, "testnet") == TESTNET_P2SH
    for mainnet in (BC1, P2PKH, P2SH, TAPROOT):
        assert is_btc_address_for_network(mainnet, "testnet") is False
        assert classify_btc_address(mainnet, "testnet") == "prefix"
        assert is_btc_address_for_network(mainnet, "mainnet")
    assert is_btc_testnet_address(TB1_WRONG_CHECKSUM) is False
    assert classify_btc_address(TB1_WRONG_CHECKSUM, "testnet") == "checksum"
    assert classify_btc_address("tb1", "testnet") == "checksum"
    assert classify_btc_address("m", "testnet") == "checksum"
    assert classify_btc_address("n", "testnet") == "checksum"
    assert classify_btc_address("2", "testnet") == "checksum"
    assert "Введите BTC-адрес testnet" in address_prompt("testnet")
    assert "tb1" in address_retry_text("hello", "testnet")
    assert address_retry_text("hello", "testnet") == ADDRESS_PREFIX_HINT_TESTNET
    assert address_retry_text(TB1_WRONG_CHECKSUM, "testnet") == ADDRESS_CHECKSUM_HINT
    assert address_prompt("mainnet") == address_prompt()
    assert "bc1" in address_prompt()


def test_rejects_junk() -> None:
    for value in (
        "",
        "hello",
        "bc1",
        "1",
        "3",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5",
        BC1_TRUNCATED,
        "Bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb",
        "3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy",
        "2N4FQj7n4Z4i5i6j7k8L9m0N",
    ):
        assert is_btc_mainnet_address(value) is False


def test_error_text_does_not_blame_a_valid_prefix() -> None:
    assert is_btc_mainnet_address(BC1_TRUNCATED) is False
    assert classify_btc_mainnet_address(BC1_TRUNCATED) == "checksum"
    checksum_text = address_retry_text(BC1_TRUNCATED)
    assert checksum_text == ADDRESS_CHECKSUM_HINT
    assert "неполный" in checksum_text
    assert "контрольная сумма" in checksum_text
    assert "начина" not in checksum_text
    assert classify_btc_mainnet_address("bc1") == "checksum"
    assert classify_btc_mainnet_address("1") == "checksum"
    assert classify_btc_mainnet_address("3") == "checksum"
    assert classify_btc_mainnet_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb") == "checksum"
    assert classify_btc_mainnet_address("3J98t1WpEZ73CNmYviecrnyiWrnqRhWNLy") == "checksum"
    assert address_retry_text("bc1") == ADDRESS_CHECKSUM_HINT
    assert address_retry_text("hello") == ADDRESS_PREFIX_HINT
    assert classify_btc_mainnet_address("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == "prefix"
    assert "bc1" in address_retry_text("not-an-address")


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
