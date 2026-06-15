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
TIME_PERIODS_PM = {"下午", "晚上", "今晚", "傍晚"}
TIME_PERIODS_AM = {"凌晨", "早上", "早晨", "上午", "明早"}
TIME_PERIODS_NOON = {"中午"}


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def cn_number_to_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in CN_NUMBERS:
        return CN_NUMBERS[value]
    if "十" in value:
        left, _, right = value.partition("十")
        tens = CN_NUMBERS.get(left, 1) if left else 1
        ones = CN_NUMBERS.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def _normalize_hour(period: str | None, hour: int) -> int:
    if period in TIME_PERIODS_PM and hour < 12:
        return hour + 12
    if period in TIME_PERIODS_NOON and hour < 11:
        return hour + 12
    if period in TIME_PERIODS_AM and hour == 12:
        return 0
    return hour


def _parse_time_prefix(text: str) -> tuple[str | None, str]:
    raw = text.strip()
    if not raw:
        return None, raw

    hhmm_match = re.match(r"^(?P<time>\d{1,2}[:：]\d{2})\s*(?P<rest>.*)$", raw)
    if hhmm_match:
        time_text = hhmm_match.group("time").replace("：", ":")
        hour_text, minute_text = time_text.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}", hhmm_match.group("rest").strip()
        return None, raw

    number = r"(?:\d{1,2}|[一二两三四五六七八九十]+)"
    period = r"(?:凌晨|早上|早晨|上午|中午|下午|晚上|今晚|傍晚|明早)?"
    point_match = re.match(
        rf"^(?P<period>{period})\s*(?P<hour>{number})\s*点"
        rf"(?:(?P<minute>半|\d{{1,2}}|[一二两三四五六七八九十]+)\s*分?)?\s*(?P<rest>.*)$",
        raw,
    )
    if not point_match:
        return None, raw

    hour = cn_number_to_int(point_match.group("hour"))
    minute_text = point_match.group("minute") or ""
    if minute_text == "半":
        minute = 30
    elif minute_text:
        minute = cn_number_to_int(minute_text)
    else:
        minute = 0
    if hour is None or minute is None:
        return None, raw
    hour = _normalize_hour(point_match.group("period") or None, hour)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, raw
    return f"{hour:02d}:{minute:02d}", point_match.group("rest").strip()


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
    duration_number = r"(?:\d+|[一二两三四五六七八九十]+)"
    minute_match = re.match(rf"^(?P<num>{duration_number})\s*(?:分钟|分)(?:后|之后|内)?\s*(?P<rest>.*)$", raw)
    if minute_match:
        minutes = cn_number_to_int(minute_match.group("num"))
        if minutes is None:
            return None, raw
        parsed = (current + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
        return parsed, minute_match.group("rest").strip()

    half_hour_match = re.match(r"^半\s*(?:小时|钟头)(?:后|之后|内)?\s*(?P<rest>.*)$", raw)
    if half_hour_match:
        parsed = (current + timedelta(minutes=30)).replace(second=0, microsecond=0)
        return parsed, half_hour_match.group("rest").strip()

    hour_match = re.match(rf"^(?P<num>{duration_number})\s*(?:小时|钟头)(?:后|之后|内)?\s*(?P<rest>.*)$", raw)
    if hour_match:
        hours = cn_number_to_int(hour_match.group("num"))
        if hours is None:
            return None, raw
        parsed = (current + timedelta(hours=hours)).replace(second=0, microsecond=0)
        return parsed, hour_match.group("rest").strip()

    patterns = [
        (r"^(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*(?P<rest>.*)$", None),
        (r"^(?P<date>\d{1,2}[-/]\d{1,2})\s*(?P<rest>.*)$", None),
    ]
    for pattern, _ in patterns:
        match = re.match(pattern, raw)
        if not match:
            continue
        date_text = match.group("date")
        time_text, final_rest = _parse_time_prefix(match.group("rest"))
        time_text = time_text or "12:00"
        parsed_date = parse_date(date_text)
        if not parsed_date:
            continue
        parsed = parse_datetime(f"{parsed_date} {time_text}")
        return parsed, final_rest

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
            time_text, final_rest = _parse_time_prefix(rest)
            time_text = time_text or "12:00"
            due_date = current + timedelta(days=days)
            parsed = parse_datetime(f"{due_date.strftime('%Y-%m-%d')} {time_text}")
            return parsed, final_rest

    day_match = re.match(r"^(?P<num>\d+|[一二两三四五六七八九十]+)\s*天(?:后|内)?\s*(?P<rest>.*)$", raw)
    if day_match:
        num_text = day_match.group("num")
        days = cn_number_to_int(num_text)
        if days is None:
            return None, raw
        due_date = current + timedelta(days=days)
        time_text, final_rest = _parse_time_prefix(day_match.group("rest"))
        time_text = time_text or "12:00"
        parsed = parse_datetime(f"{due_date.strftime('%Y-%m-%d')} {time_text}")
        return parsed, final_rest

    return None, raw


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def combine_today(hhmm: str, base: datetime | None = None) -> datetime:
    base = base or now_local()
    return datetime.combine(base.date(), parse_hhmm(hhmm))
