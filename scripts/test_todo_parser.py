from datetime import timedelta

import nonebot
from sqlalchemy import inspect

from src.db import engine, init_db
from src.time_utils import DateTimeParseError, now_local, parse_natural_datetime_prefix
from src.todo_service import TodoParseError, parse_todo_request


nonebot.init()
from src.plugins.todo import _parse_add_payload  # noqa: E402


def assert_parsed(text: str, content: str, lead: int | None = 15) -> None:
    parsed = parse_todo_request(text, allow_plain_time=True)
    assert parsed is not None, text
    assert parsed.content == content, (text, parsed)
    assert parsed.lead_remind_minutes == lead, (text, parsed)


def main() -> None:
    init_db()
    columns = {column["name"] for column in inspect(engine).get_columns("todos")}
    assert "lead_remind_minutes" in columns
    assert "last_lead_reminded_at" in columns

    assert_parsed("晚上六点检查卫生", "检查卫生")
    assert_parsed("明天晚上六点检查卫生", "检查卫生")
    assert_parsed("提前20分钟晚上六点检查卫生", "检查卫生", 20)
    assert_parsed("三天后我有一个考试，记得每天提醒我", "考试")

    short = parse_todo_request("10分钟 学习 5分钟", allow_plain_time=True)
    assert short is not None
    assert short.content == "学习 5分钟"
    assert short.lead_remind_minutes is None
    assert short.due_at - now_local() <= timedelta(minutes=10, seconds=5)

    ranged = parse_todo_request("明天 09:00-11:00 高数作业", allow_plain_time=True)
    assert ranged is not None
    assert ranged.content == "高数作业"
    assert ranged.start_at is not None
    assert ranged.end_at is not None
    assert ranged.start_at.hour == 9
    assert ranged.end_at.hour == 11

    add_content, due_at, start_at, end_at, _repeat, lead, error = _parse_add_payload("明天 09:00-11:00 高数作业")
    assert error is None
    assert add_content == ranged.content
    assert due_at == ranged.due_at
    assert start_at == ranged.start_at
    assert end_at == ranged.end_at
    assert lead == ranged.lead_remind_minutes

    try:
        parse_natural_datetime_prefix("明天 24:00 开会")
    except DateTimeParseError:
        pass
    else:
        raise AssertionError("invalid time should raise DateTimeParseError")

    for text in ["明天 99:00 开会", "2026-06-18 99:00 开会"]:
        try:
            parse_todo_request(text, allow_plain_time=True)
        except DateTimeParseError:
            pass
        else:
            raise AssertionError(f"invalid time should fail: {text}")

    try:
        parse_todo_request("明天 09:00 开会 每 0 分钟", allow_plain_time=True)
    except TodoParseError:
        pass
    else:
        raise AssertionError("invalid repeat interval should fail")

    print("TODO_PARSER_TEST_OK")


if __name__ == "__main__":
    main()
