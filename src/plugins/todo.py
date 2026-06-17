import re
from datetime import datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg
from sqlalchemy import select

from src.db import Todo, init_db, session_scope
from src.time_utils import now_local, parse_datetime, parse_natural_datetime_prefix
from src.todo_service import (
    DEFAULT_LEAD_REMIND_MINUTES,
    add_todo,
    normalize_todo_text,
    parse_repeat_interval,
    parse_todo_request,
)


todo_cmd = on_command("todo", priority=20, block=True)


def _format_interval(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"，每 {days} 天提醒"
    return f"，每 {minutes} 分钟提醒"


def _format_lead_reminder(minutes: int | None) -> str:
    if not minutes:
        return ""
    if minutes % 60 == 0:
        return f"，提前 {minutes // 60} 小时提醒"
    return f"，提前 {minutes} 分钟提醒"


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


def _parse_add_payload(
    payload: str,
) -> tuple[str, datetime | None, datetime | None, datetime | None, int | None, int | None, str | None]:
    natural = parse_todo_request(payload, allow_plain_time=True)
    natural_lead = natural.lead_remind_minutes if natural else None
    due_at, rest = parse_natural_datetime_prefix(payload)
    start_at, end_at, range_rest = _parse_time_range_payload(payload)
    if start_at or end_at:
        due_at = end_at
        content = range_rest.strip()
    else:
        due_at, rest = _parse_due_payload(payload)
        content = rest.strip() if due_at else payload.strip()
    remind_every = parse_repeat_interval(content)
    if remind_every is None and natural:
        remind_every = natural.remind_every_minutes

    remind_match = None
    for marker in [" remind "]:
        if remind_every is None and marker in content:
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
            return "", None, None, None, None, None, "提醒间隔格式不正确，例如：/todo add 三天 大作业 每 1 天"
        if remind_every < 1:
            return "", None, None, None, None, None, "提醒间隔必须大于 0。"

    content = normalize_todo_text(content)
    if not content:
        if natural:
            return (
                natural.content,
                natural.due_at,
                natural.start_at,
                natural.end_at,
                natural.remind_every_minutes,
                natural.lead_remind_minutes,
                None,
            )
        return "", None, None, None, None, None, "todo 内容不能为空。"
    if start_at and end_at and end_at < start_at:
        return "", None, None, None, None, None, "todo 结束时间不能早于开始时间。"
    if natural and due_at is None and start_at is None and end_at is None:
        return (
            natural.content,
            natural.due_at,
            natural.start_at,
            natural.end_at,
            natural.remind_every_minutes,
            natural.lead_remind_minutes,
            None,
        )
    if due_at and natural_lead is None:
        natural_lead = DEFAULT_LEAD_REMIND_MINUTES
    return content, due_at, start_at, end_at, remind_every, natural_lead, None


def _find_todo(session, group_id: str, user_id: str, target: str):
    target = target.strip()
    if not target:
        return None, "请提供任务 ID 或任务名称。"
    if target.isdigit():
        todo = session.scalar(
            select(Todo).where(Todo.id == int(target), Todo.group_id == group_id, Todo.user_id == user_id)
        )
        if todo is None:
            return None, f"没有找到 todo #{target}，或它不属于你。"
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


def _format_added_todo_time(due_at: datetime | None, start_at: datetime | None, end_at: datetime | None) -> str:
    if start_at and end_at:
        if start_at.date() == end_at.date():
            return f"{start_at:%Y-%m-%d %H:%M}-{end_at:%H:%M}"
        return f"{start_at:%Y-%m-%d %H:%M} 至 {end_at:%Y-%m-%d %H:%M}"
    if start_at:
        return f"开始 {start_at:%Y-%m-%d %H:%M}"
    if due_at:
        return f"截止 {due_at:%Y-%m-%d %H:%M}"
    return "无截止时间，不会触发到点提醒"


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

    if action in {"add", "添加", "新增"}:
        content, due_at, start_at, end_at, remind_every, lead_remind, error = _parse_add_payload(payload)
        if error:
            await todo_cmd.finish(error)
        todo_id = add_todo(group_id, user_id, content, due_at, remind_every, start_at, end_at, lead_remind)
        time_text = _format_added_todo_time(due_at, start_at, end_at)
        interval = _format_interval(remind_every)
        lead = _format_lead_reminder(lead_remind)
        await todo_cmd.finish(f"已添加 todo #{todo_id}：{content}（{time_text}{interval}{lead}）。")

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
            lead = _format_lead_reminder(todo.lead_remind_minutes)
            lines.append(f"#{todo.id} {todo.content}（{due}{interval}{lead}）")
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

    natural = parse_todo_request(raw, allow_plain_time=True)
    if natural:
        todo_id = add_todo(
            group_id,
            user_id,
            natural.content,
            natural.due_at,
            natural.remind_every_minutes,
            natural.start_at,
            natural.end_at,
            natural.lead_remind_minutes,
        )
        time_text = _format_added_todo_time(natural.due_at, natural.start_at, natural.end_at)
        interval = _format_interval(natural.remind_every_minutes)
        lead = _format_lead_reminder(natural.lead_remind_minutes)
        await todo_cmd.finish(f"已添加 todo #{todo_id}：{natural.content}（{time_text}{interval}{lead}）。")

    await todo_cmd.finish("未知 todo 命令。可用：add/list/done/delete；也可以直接写 /todo 晚上六点检查卫生")
