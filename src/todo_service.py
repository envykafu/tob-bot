import re
from datetime import datetime

from src.db import Todo, session_scope
from src.time_utils import parse_natural_datetime_prefix


REMINDER_HINTS = ("提醒", "截止", "ddl", "DDL", "待办", "todo", "Todo", "作业", "任务")
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
    cleaned = re.sub(r"(记得)?\s*提醒我[一下]?", "", cleaned).strip()
    cleaned = re.sub(r"(要)?截止了?$", "", cleaned).strip()
    cleaned = re.sub(r"我有一个|我有个|我有|我要", "", cleaned).strip()
    cleaned = re.sub(r"有一个", "", cleaned).strip()
    cleaned = re.sub(r"有个", "", cleaned).strip()
    cleaned = re.sub(r"^有", "", cleaned).strip()
    cleaned = re.sub(r"要截止", "", cleaned).strip()
    cleaned = re.sub(r"截止", "", cleaned).strip()
    cleaned = cleaned.strip("，,。.!！ ")
    return cleaned


def parse_todo_from_text(text: str) -> tuple[str, datetime | None] | None:
    if not looks_like_todo_request(text):
        return None
    due_at, rest = parse_natural_datetime_prefix(normalize_todo_text(text))
    if not due_at:
        return None
    content = normalize_todo_text(rest)
    if not content:
        return None
    return content, due_at


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
        )
        session.add(todo)
        session.flush()
        return todo.id
