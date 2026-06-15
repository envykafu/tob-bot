import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.config import settings


TZ = ZoneInfo(settings.timezone)
CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%m-%d %H:%M",
        "%m/%d %H:%M",
    ]
    current = now_local()
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            parsed = parsed.replace(year=current.year)
        return parsed
    return None


def default_noon(value: datetime) -> datetime:
    return value.replace(hour=12, minute=0, second=0, microsecond=0)


def parse_date(value: str) -> str | None:
    value = value.strip()
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d"]
    current = now_local()
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            parsed = parsed.replace(year=current.year)
        return parsed.strftime("%Y-%m-%d")
    return None


def parse_date_or_today(value: str) -> str | None:
    lowered = value.strip()
    current = now_local()
    if lowered in {"今天", "今日"}:
        return current.strftime("%Y-%m-%d")
    if lowered in {"明天", "明日"}:
        return (current + timedelta(days=1)).strftime("%Y-%m-%d")
    if lowered in {"后天"}:
        return (current + timedelta(days=2)).strftime("%Y-%m-%d")
    return parse_date(value)


def parse_natural_datetime_prefix(text: str) -> tuple[datetime | None, str]:
    raw = text.strip()
    current = now_local()
    patterns = [
        (r"^(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})(?:\s+(?P<time>\d{1,2}:\d{2}))?\s*(?P<rest>.*)$", None),
        (r"^(?P<date>\d{1,2}[-/]\d{1,2})(?:\s+(?P<time>\d{1,2}:\d{2}))?\s*(?P<rest>.*)$", None),
    ]
    for pattern, _ in patterns:
        match = re.match(pattern, raw)
        if not match:
            continue
        date_text = match.group("date")
        time_text = match.group("time") or "12:00"
        parsed_date = parse_date(date_text)
        if not parsed_date:
            continue
        parsed = parse_datetime(f"{parsed_date} {time_text}")
        return parsed, match.group("rest").strip()

    relative = [
        ("今天", 0),
        ("今日", 0),
        ("明天", 1),
        ("明日", 1),
        ("后天", 2),
    ]
    for word, days in relative:
        if raw.startswith(word):
            rest = raw[len(word):].strip()
            time_match = re.match(r"^(?P<time>\d{1,2}:\d{2})\s*(?P<rest>.*)$", rest)
            time_text = time_match.group("time") if time_match else "12:00"
            final_rest = time_match.group("rest").strip() if time_match else rest
            due_date = current + timedelta(days=days)
            parsed = parse_datetime(f"{due_date.strftime('%Y-%m-%d')} {time_text}")
            return parsed, final_rest

    day_match = re.match(r"^(?P<num>\d+|[一二两三四五六七八九十])\s*天(?:后|内)?(?:\s*(?P<time>\d{1,2}:\d{2}))?\s*(?P<rest>.*)$", raw)
    if day_match:
        num_text = day_match.group("num")
        days = int(num_text) if num_text.isdigit() else CN_NUMBERS[num_text]
        due_date = current + timedelta(days=days)
        time_text = day_match.group("time") or "12:00"
        parsed = parse_datetime(f"{due_date.strftime('%Y-%m-%d')} {time_text}")
        return parsed, day_match.group("rest").strip()

    return None, raw


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def combine_today(hhmm: str, base: datetime | None = None) -> datetime:
    base = base or now_local()
    return datetime.combine(base.date(), parse_hhmm(hhmm))
