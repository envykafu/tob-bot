import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.db import Todo, session_scope
from src.time_utils import now_local, parse_natural_datetime_prefix, parse_next_time_prefix


REMINDER_HINTS = ("提醒", "截止", "ddl", "DDL", "待办", "todo", "Todo", "作业", "任务", "记得", "备忘")
DEFAULT_LEAD_REMIND_MINUTES = 15
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
TIME_CANDIDATE_RE = re.compile(
    r"(?:今天|今日|明天|明日|后天)?\s*"
    r"(?:(?:凌晨|早上|早晨|上午|中午|下午|晚上|今晚|傍晚|明早)\s*)?"
    r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*点(?:半|(?:\d{1,2}|[一二两三四五六七八九十]+)\s*分?)?"
    r"|(?:今天|今日|明天|明日|后天)?\s*(?:(?:凌晨|早上|早晨|上午|中午|下午|晚上|今晚|傍晚|明早)\s*)?\d{1,2}[:：]\d{2}"
)
QUESTION_HINTS = (
    "吗",
    "嘛",
    "么",
    "什么",
    "怎么",
    "为什么",
    "为啥",
    "多少",
    "几",
    "？",
    "?",
)
EMPTY_BEFORE_TIME = {"", "我", "俺", "咱", "我在", "俺在", "咱在"}


@dataclass(frozen=True)
class ParsedTodoRequest:
    content: str
    due_at: datetime | None
    remind_every_minutes: int | None = None
    lead_remind_minutes: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


def looks_like_todo_request(text: str) -> bool:
    return any(hint in text for hint in REMINDER_HINTS)


def _cn_number_to_int(value: str) -> int | None:
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


def normalize_todo_text(text: str) -> str:
    cleaned = text.strip()
    repeat_unit = r"(?:天|日|分钟|分|小时|钟头|周|星期|礼拜)"
    repeat_num = r"(?:\d+|[一二两三四五六七八九十]+)?"
    cleaned = re.sub(
        rf"[，,。；;]?\s*(记得)?\s*每\s*{repeat_num}\s*{repeat_unit}\s*(提醒)?(我)?(一下|一次)?",
        "",
        cleaned,
    ).strip()
    cleaned = re.sub(r"[，,。；;]?\s*(记得)?\s*每\s*(天|日|日早|天早)\s*(提醒)?(我)?(一下|一次)?", "", cleaned).strip()
    cleaned = re.sub(r"[，,。；;]?\s*(记得)?\s*每日\s*(提醒)?(我)?(一下|一次)?", "", cleaned).strip()
    cleaned = re.sub(r"^(请|帮我|麻烦|记得|到时候|一定要)+", "", cleaned).strip()
    cleaned = re.sub(r"^(在|于|到|截至|截止到)\s*", "", cleaned).strip()
    cleaned = re.sub(r"(记得)?\s*提醒我[一下]?", "", cleaned).strip()
    cleaned = re.sub(r"^(提醒我|提醒一下我|提醒)\s*", "", cleaned).strip()
    cleaned = re.sub(r"(要)?截止了?$", "", cleaned).strip()
    cleaned = re.sub(r"我有一个|我有个|我有|我要", "", cleaned).strip()
    cleaned = re.sub(r"有一个", "", cleaned).strip()
    cleaned = re.sub(r"有个", "", cleaned).strip()
    cleaned = re.sub(r"^有", "", cleaned).strip()
    cleaned = re.sub(r"要截止", "", cleaned).strip()
    cleaned = re.sub(r"截止", "", cleaned).strip()
    cleaned = cleaned.strip("，,。.!！ ")
    return cleaned


def _looks_like_question(text: str) -> bool:
    return any(hint in text for hint in QUESTION_HINTS)


def _parse_lead_remind_minutes(text: str) -> tuple[int | None, str]:
    patterns = [
        r"(?:提前|提早)\s*(?P<num>\d+|[一二两三四五六七八九十]+)\s*(?P<unit>分钟|分|小时|钟头)\s*(?:提醒)?",
        r"(?:提前|提早)\s*半\s*(?P<half_unit>小时|钟头)\s*(?:提醒)?",
    ]
    cleaned = text
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        if match.groupdict().get("half_unit"):
            minutes = 30
        else:
            number = _cn_number_to_int(match.group("num"))
            if number is None:
                return None, cleaned
            unit = match.group("unit")
            minutes = number * 60 if unit in {"小时", "钟头"} else number
        cleaned = (cleaned[: match.start()] + cleaned[match.end() :]).strip()
        return max(1, minutes), cleaned
    return None, cleaned


def _parse_due_and_content(text: str) -> tuple[datetime | None, str]:
    parsed, rest = parse_natural_datetime_prefix(text)
    if parsed:
        return parsed, rest
    parsed, rest = parse_next_time_prefix(text)
    if parsed:
        return parsed, rest

    for match in TIME_CANDIDATE_RE.finditer(text):
        candidate = text[match.start() :].strip()
        parsed, rest = parse_natural_datetime_prefix(candidate)
        if not parsed:
            parsed, rest = parse_next_time_prefix(candidate)
        if not parsed:
            continue
        before = normalize_todo_text(text[: match.start()].strip())
        after = normalize_todo_text(rest)
        if before in EMPTY_BEFORE_TIME:
            before = ""
        content = before or after
        if before and after:
            content = f"{before} {after}".strip()
        if content:
            return parsed, content
    return None, text


def parse_todo_request(text: str, allow_plain_time: bool = False) -> ParsedTodoRequest | None:
    raw = text.strip()
    if not raw:
        return None
    has_hint = looks_like_todo_request(raw)
    lead_remind, without_lead = _parse_lead_remind_minutes(raw)
    remind_every = parse_repeat_interval(without_lead)
    normalized = normalize_todo_text(without_lead)
    due_at, rest = _parse_due_and_content(normalized)
    if not due_at:
        return None
    content = normalize_todo_text(rest)
    if not content:
        return None
    if not has_hint and not allow_plain_time and _looks_like_question(raw):
        return None
    if not has_hint and not allow_plain_time and len(content) < 2:
        return None
    if lead_remind is None and due_at - now_local() > timedelta(minutes=DEFAULT_LEAD_REMIND_MINUTES):
        lead_remind = DEFAULT_LEAD_REMIND_MINUTES
    return ParsedTodoRequest(
        content=content,
        due_at=due_at,
        remind_every_minutes=remind_every,
        lead_remind_minutes=lead_remind,
    )


def parse_todo_from_text(text: str) -> tuple[str, datetime | None] | None:
    parsed = parse_todo_request(text)
    if not parsed:
        return None
    return parsed.content, parsed.due_at


def parse_repeat_interval(text: str) -> int | None:
    match = re.search(r"每\s*(天|日)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        return 1440
    match = re.search(r"每日\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        return 1440
    match = re.search(r"每\s*(小时|钟头)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        return 60
    match = re.search(r"每\s*(周|星期|礼拜)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        return 10080
    match = re.search(r"每\s*(\d+|[一二两三四五六七八九十]+)\s*(天|日)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        number = _cn_number_to_int(match.group(1))
        return number * 1440 if number else None
    match = re.search(r"每\s*(\d+|[一二两三四五六七八九十]+)\s*(小时|钟头)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        number = _cn_number_to_int(match.group(1))
        return number * 60 if number else None
    match = re.search(r"每\s*(\d+|[一二两三四五六七八九十]+)\s*(分钟|分)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        number = _cn_number_to_int(match.group(1))
        return number if number else None
    match = re.search(r"每\s*(\d+|[一二两三四五六七八九十]+)\s*(周|星期|礼拜)\s*(提醒)?(我)?(一下|一次)?", text)
    if match:
        number = _cn_number_to_int(match.group(1))
        return number * 10080 if number else None
    return None


def add_todo(
    group_id: str,
    user_id: str,
    content: str,
    due_at: datetime | None,
    remind_every_minutes: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    lead_remind_minutes: int | None = None,
) -> int:
    with session_scope() as session:
        todo = Todo(
            group_id=group_id,
            user_id=user_id,
            content=content,
            start_at=start_at,
            end_at=end_at,
            due_at=due_at,
            remind_every_minutes=remind_every_minutes,
            lead_remind_minutes=lead_remind_minutes,
        )
        session.add(todo)
        session.flush()
        return todo.id
