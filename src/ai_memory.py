import json
from typing import Any

from src.config import settings
from src.db import AIConversation, session_scope
from src.time_utils import now_local


def _normalize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    max_messages = settings.ai_context_messages
    return normalized[-max_messages:]


def load_context(bot_message_id: int | str | None) -> list[dict[str, str]]:
    if bot_message_id is None:
        return []
    with session_scope() as session:
        item = (
            session.query(AIConversation)
            .filter(AIConversation.bot_message_id == str(bot_message_id))
            .one_or_none()
        )
        if item is None:
            return []
        try:
            raw_messages: Any = json.loads(item.messages_json or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(raw_messages, list):
            return []
        return _normalize_messages(raw_messages)


def save_context(
    *,
    group_id: str,
    user_id: str,
    bot_message_id: int | str | None,
    parent_bot_message_id: int | str | None,
    messages: list[dict[str, str]],
) -> None:
    if bot_message_id is None:
        return
    normalized = _normalize_messages(messages)
    if not normalized:
        return
    now = now_local()
    with session_scope() as session:
        session.merge(
            AIConversation(
                bot_message_id=str(bot_message_id),
                parent_bot_message_id=str(parent_bot_message_id or ""),
                group_id=group_id,
                user_id=user_id,
                messages_json=json.dumps(normalized, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
        )
