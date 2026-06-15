import re
from datetime import datetime

from src.db import Todo, session_scope
from src.time_utils import parse_natural_datetime_prefix


REMINDER_HINTS = ("提醒", "截止", "ddl", "DDL", "待办", "todo", "Todo", "作业", "任务")


def looks_like_todo_request(text: str) -> bool:
    return any(hint in text for hint in REMINDER_HINTS)


def normalize_todo_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"[，,]?\s*每\s*\d+\s*(天|日|分钟|分)\s*(提醒)?(我)?(一次)?", "", cleaned).strip()
    cleaned = re.sub(r"^(请|帮我|麻烦|记得|到时候|一定要)+", "", cleaned).strip()
    cleaned = re.sub(r"(记得)?提醒我[一下]?", "", cleaned).strip()
    cleaned = re.sub(r"(要)?截止了?$", "", cleaned).strip()
    cleaned = re.sub(r"有一个", "", cleaned).strip()
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
    match = re.search(r"每\s*(\d+)\s*(天|日)\s*(提醒)?(我)?(一次)?", text)
    if match:
        return int(match.group(1)) * 1440
    match = re.search(r"每\s*(\d+)\s*(分钟|分)\s*(提醒)?(我)?(一次)?", text)
    if match:
        return int(match.group(1))
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
