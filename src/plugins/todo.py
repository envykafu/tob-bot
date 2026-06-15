import re
from datetime import datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg
from sqlalchemy import select

from src.db import Todo, init_db, session_scope
from src.time_utils import now_local, parse_datetime, parse_natural_datetime_prefix
from src.todo_service import add_todo


todo_cmd = on_command("todo", priority=20, block=True)


def _format_interval(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"，每 {days} 天提醒"
    return f"，每 {minutes} 分钟提醒"


def _parse_todo_datetime(text: str) -> tuple[datetime | None, str]:
    parsed, rest = parse_natural_datetime_prefix(text)
    if parsed:
        return parsed, rest
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2:
        parsed = parse_datetime(parts[0])
        if parsed:
            return parsed, parts[1].strip()
    return None, text.strip()


def _parse_time_range_payload(payload: str) -> tuple[datetime | None, datetime | None, str]:
    start_at = None
    end_at = None
    content = payload.strip()

    explicit = re.match(
        r"^(?:start|开始|起始)\s+(?P<start>.+?)\s+(?:end|结束|截止)\s+(?P<end>.+?)\s+(?P<content>.+)$",
        content,
        re.IGNORECASE,
    )
    if explicit:
        start_at, start_rest = _parse_todo_datetime(explicit.group("start"))
        end_at, end_rest = _parse_todo_datetime(explicit.group("end"))
        if start_at and end_at and not start_rest and not end_rest:
            return start_at, end_at, explicit.group("content").strip()

    range_match = re.match(
        r"^(?P<date>(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}|今天|今日|明天|明日|后天))\s+"
        r"(?P<start>\d{1,2}:\d{2})\s*[-~至到]\s*(?P<end>\d{1,2}:\d{2})\s+(?P<content>.+)$",
        content,
    )
    if range_match:
        start_at, _ = parse_natural_datetime_prefix(f"{range_match.group('date')} {range_match.group('start')}")
        end_at, _ = parse_natural_datetime_prefix(f"{range_match.group('date')} {range_match.group('end')}")
        if start_at and end_at:
            return start_at, end_at, range_match.group("content").strip()

    return start_at, end_at, content


def _parse_due_payload(payload: str) -> tuple[datetime | None, str]:
    content = payload.strip()
    due_match = re.match(r"^(?:due|ddl|截止)\s+(?P<due>.+?)\s+(?P<content>.+)$", content, re.IGNORECASE)
    if due_match:
        due_at, due_rest = _parse_todo_datetime(due_match.group("due"))
        if due_at and not due_rest:
            return due_at, due_match.group("content").strip()
    return parse_natural_datetime_prefix(content)


def _parse_add_payload(payload: str) -> tuple[str, datetime | None, datetime | None, datetime | None, int | None, str | None]:
    due_at, rest = parse_natural_datetime_prefix(payload)
    start_at, end_at, range_rest = _parse_time_range_payload(payload)
    if start_at or end_at:
        due_at = end_at
        content = range_rest.strip()
    else:
        due_at, rest = _parse_due_payload(payload)
        content = rest.strip() if due_at else payload.strip()
    remind_every = None

    remind_match = None
    for marker in [" 每", " remind "]:
        if marker in content:
            before, _, after = content.partition(marker)
            remind_match = after.strip()
            content = before.strip()
            break
    if remind_match:
        normalized = remind_match.replace("一次", "").strip()
        try:
            if "天" in normalized or "日" in normalized:
                remind_every = int(normalized.replace("天", "").replace("日", "").strip()) * 1440
            else:
                remind_every = int(normalized.replace("分钟", "").replace("分", "").strip())
        except ValueError:
            return "", None, None, None, None, "提醒间隔格式不正确，例如：/todo add 三天 大作业 每 1 天"
        if remind_every < 1:
            return "", None, None, None, None, "提醒间隔必须大于 0。"

    if not content:
        return "", None, None, None, None, "todo 内容不能为空。"
    if start_at and end_at and end_at < start_at:
        return "", None, None, None, None, "todo 结束时间不能早于开始时间。"
    return content, due_at, start_at, end_at, remind_every, None


def _find_todo(session, group_id: str, user_id: str, target: str):
    target = target.strip()
    if not target:
        return None, "请提供任务 ID 或任务名称。"
    if target.isdigit():
        todo = session.scalar(
            select(Todo).where(Todo.id == int(target), Todo.group_id == group_id, Todo.user_id == user_id)
        )
        return todo, None
    todos = session.scalars(
        select(Todo).where(
            Todo.group_id == group_id,
            Todo.user_id == user_id,
            Todo.done.is_(False),
            Todo.content == target,
        )
    ).all()
    if len(todos) == 1:
        return todos[0], None
    if len(todos) > 1:
        ids = ", ".join(f"#{todo.id}" for todo in todos)
        return None, f"有多个同名 todo：{ids}，请用任务 ID。"
    todos = session.scalars(
        select(Todo).where(
            Todo.group_id == group_id,
            Todo.user_id == user_id,
            Todo.done.is_(False),
            Todo.content.contains(target),
        )
    ).all()
    if len(todos) == 1:
        return todos[0], None
    if len(todos) > 1:
        ids = ", ".join(f"#{todo.id} {todo.content}" for todo in todos[:5])
        return None, f"匹配到多个 todo：{ids}，请用更完整名称或任务 ID。"
    return None, "没有找到这个 todo，或它不属于你。"


def _format_todo_time(todo: Todo) -> str:
    if todo.start_at and todo.end_at:
        if todo.start_at.date() == todo.end_at.date():
            return f"{todo.start_at:%Y-%m-%d %H:%M}-{todo.end_at:%H:%M}"
        return f"{todo.start_at:%Y-%m-%d %H:%M} 至 {todo.end_at:%Y-%m-%d %H:%M}"
    if todo.start_at:
        return f"开始 {todo.start_at:%Y-%m-%d %H:%M}"
    if todo.due_at:
        return f"截止 {todo.due_at:%Y-%m-%d %H:%M}"
    return "无截止时间"


@todo_cmd.handle()
async def handle_todo(event: GroupMessageEvent, args: Message = CommandArg()):
    init_db()
    raw = args.extract_plain_text().strip()
    if not raw:
        await todo_cmd.finish("用法：/todo add 明天 09:00-11:00 大作业；/todo add 截止 明天20:00 大作业；未写具体时间默认中午 12:00")

    action, _, payload = raw.partition(" ")
    action = action.lower()
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    if action == "add":
        content, due_at, start_at, end_at, remind_every, error = _parse_add_payload(payload)
        if error:
            await todo_cmd.finish(error)
        todo_id = add_todo(group_id, user_id, content, due_at, remind_every, start_at, end_at)
        await todo_cmd.finish(f"已添加 todo #{todo_id}。")

    if action == "list":
        with session_scope() as session:
            todos = session.scalars(
                select(Todo)
                .where(Todo.group_id == group_id, Todo.user_id == user_id, Todo.done.is_(False))
                .order_by(Todo.due_at.is_(None), Todo.due_at, Todo.id)
            ).all()
        if not todos:
            await todo_cmd.finish("你当前没有未完成 todo。")
        lines = ["你的未完成 todo："]
        for todo in todos:
            due = _format_todo_time(todo)
            interval = _format_interval(todo.remind_every_minutes)
            lines.append(f"#{todo.id} {todo.content}（{due}{interval}）")
        await todo_cmd.finish("\n".join(lines))

    if action in {"done", "delete"}:
        with session_scope() as session:
            todo, error = _find_todo(session, group_id, user_id, payload)
            if error:
                await todo_cmd.finish(error)
            if action == "done":
                todo.done = True
                todo.updated_at = now_local()
                result = f"已完成 todo #{todo.id}。"
            else:
                todo_id = todo.id
                session.delete(todo)
                result = f"已删除 todo #{todo_id}。"
        await todo_cmd.finish(result)

    await todo_cmd.finish("未知 todo 命令。可用：add/list/done/delete")
