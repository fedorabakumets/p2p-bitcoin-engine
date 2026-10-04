from decimal import Decimal, ROUND_HALF_UP

MAX_RUB = Decimal(100_000_000)


def parse_rub_to_kop(text: str) -> int:
    raw = text.strip().lower().replace("\u00a0", "").replace(" ", "")
    for suffix in ("руб.", "рублей", "рубля", "руб", "₽", "rub"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    raw = raw.replace(",", ".")
    if not raw or raw.count(".") > 1:
        raise ValueError("bad amount")
    whole, dot, frac = raw.partition(".")
    if not whole.isdigit() or (dot and (not frac.isdigit() or len(frac) > 2)):
        raise ValueError("bad amount")
    amount = Decimal(raw)
    if amount <= 0 or amount > MAX_RUB:
        raise ValueError("bad amount")
    kopecks = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if kopecks <= 0:
        raise ValueError("bad amount")
    return kopecks
