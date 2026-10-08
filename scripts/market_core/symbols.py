from __future__ import annotations

import re


SH_INDEX_CODES = {"000010", "000016", "000300", "000688", "000852", "000905"}
_CN_SYMBOL = re.compile(
    r"^(?:(sh|sz|bj)(\d{6})|(\d{6})(?:\.(sh|sz|bj))?)$", re.IGNORECASE
)


def _natural_market(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "bj"
    if code.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def normalize_cn_symbol(value: str, *, stock_only: bool = False) -> str:
    """Return a market-qualified symbol such as ``sh600519``.

    Ambiguous 000xxx symbols retain an explicit market qualifier. Bare benchmark
    codes in ``SH_INDEX_CODES`` route to Shanghai; other bare 000xxx codes route
    to Shenzhen. Contradictory qualifiers fail closed.
    """

    raw = str(value).strip()
    match = _CN_SYMBOL.fullmatch(raw)
    if not match:
        raise ValueError(
            f"Unsupported China symbol {value!r}; use 600519, sh600519, or 600519.SH"
        )
    digits = match.group(2) or match.group(3)
    explicit = (match.group(1) or match.group(4) or "").lower()
    if stock_only and (digits.startswith(("399","93")) or digits.startswith(("15", "16", "50", "51", "52", "56", "58"))):
        raise ValueError(f"{value!r} is an index or fund, not an individual stock")

    if digits.startswith("000"):
        if explicit == "bj":
            raise ValueError(f"Contradictory market prefix for {value!r}")
        market = explicit or ("sh" if digits in SH_INDEX_CODES else "sz")
        if stock_only and market == "sh":
            raise ValueError(f"{value!r} resolves to a Shanghai index, not an A-share stock")
    else:
        natural = _natural_market(digits)
        if explicit and explicit != natural:
            raise ValueError(
                f"Contradictory market prefix for {value!r}; code belongs to {natural}"
            )
        market = explicit or natural
    return f"{market}{digits}"


def cn_digits(value: str, *, stock_only: bool = False) -> str:
    return normalize_cn_symbol(value, stock_only=stock_only)[2:]


def eastmoney_secid(value: str) -> str:
    symbol = normalize_cn_symbol(value)
    market_id = "1" if symbol.startswith("sh") else "0"
    return f"{market_id}.{symbol[2:]}"


def is_cn_index(value):
    symbol=normalize_cn_symbol(value)
    return symbol.startswith(("sh000","sh93","sz399"))


def is_cn_exchange_fund(value):
    symbol=normalize_cn_symbol(value)
    return symbol.startswith(('sh5','sz15','sz16'))
