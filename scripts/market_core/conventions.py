from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def interval_name(value):
    aliases = {"d": "1d", "1day": "1d", "w": "1w", "1week": "1w",
               "m": "1mo", "1month": "1mo", "5": "5m", "15": "15m", "30": "30m", "60": "60m",
               "1min":"1m","2min":"2m","5min":"5m","15min":"15m","30min":"30m","60min":"60m"}
    return aliases.get(str(value), str(value))


def price_basis_name(value):
    return {"none": "unadjusted", "": "unknown"}.get(str(value), str(value))


def parse_time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result

