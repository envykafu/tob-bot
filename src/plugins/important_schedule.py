from datetime import datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg
from sqlalchemy import select

from src.db import ImportantSchedule, init_db, session_scope
from src.time_utils import now_local, parse_date_or_today


schedule_cmd = on_command("schedule", aliases={"重要日程"}, priority=20, block=True)
add_schedule_cmd = on_command("添加重要日程", priority=20, block=True)
list_schedule_cmd = on_command("查看重要日程", priority=20, block=True)
delete_schedule_cmd = on_command("删除重要日程", priority=20, block=True)


def _days_left(target_date: str) -> int | None:
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (target - now_local().date()).days


def _format_countdown(target_date: str) -> str:
    days_left = _days_left(target_date)
    if days_left is None:
        return target_date
    if days_left < 0:
        return f"{target_date}，已过期"
    if days_left == 0:
        return f"{target_date}，就是今天"
    return f"{target_date}，还有 {days_left} 天"


def _find_schedule(session, group_id: str, user_id: str, target: str):
    target = target.strip()
    if not target:
        return None, "请提供日程 ID 或名称。"
    if target.isdigit():
        schedule = session.scalar(
            select(ImportantSchedule).where(
                ImportantSchedule.id == int(target),
                ImportantSchedule.group_id == group_id,
                ImportantSchedule.user_id == user_id,
            )
        )
        return schedule, None
    schedules = session.scalars(
        select(ImportantSchedule).where(
            ImportantSchedule.group_id == group_id,
            ImportantSchedule.user_id == user_id,
            ImportantSchedule.enabled.is_(True),
            ImportantSchedule.title.contains(target),
        )
    ).all()
    if len(schedules) == 1:
        return schedules[0], None
    if len(schedules) > 1:
        items = ", ".join(f"#{item.id} {item.title}" for item in schedules[:5])
        return None, f"匹配到多个重要日程：{items}，请使用日程 ID。"
    return None, "没有找到这个重要日程。"


async def _handle_schedule(event: GroupMessageEvent, raw: str):
    init_db()
    action, _, payload = raw.strip().partition(" ")
    action = action.lower()
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    if action in {"add", "添加"}:
        parts = payload.split(maxsplit=1)
        if len(parts) < 2:
            return "用法：/重要日程 add 2026-06-20 考试"
        target_date = parse_date_or_today(parts[0])
        if not target_date:
            return "日期格式不正确，例如 2026-06-20、明天。"
        title = parts[1].strip()
        if not title:
            return "重要日程名称不能为空。"
        with session_scope() as session:
            schedule = ImportantSchedule(
                group_id=group_id,
                user_id=user_id,
                title=title,
                target_date=target_date,
            )
            session.add(schedule)
            session.flush()
            schedule_id = schedule.id
        return f"已添加重要日程 #{schedule_id}：{title}（{_format_countdown(target_date)}）。每天 08:00 提醒。"

    if action in {"list", "查看"}:
        with session_scope() as session:
            schedules = session.scalars(
                select(ImportantSchedule)
                .where(
                    ImportantSchedule.group_id == group_id,
                    ImportantSchedule.user_id == user_id,
                    ImportantSchedule.enabled.is_(True),
                )
                .order_by(ImportantSchedule.target_date, ImportantSchedule.id)
            ).all()
        if not schedules:
            return "你当前没有重要日程。"
        lines = ["你的重要日程："]
        for schedule in schedules:
            lines.append(f"#{schedule.id} {schedule.title}（{_format_countdown(schedule.target_date)}）")
        return "\n".join(lines)

    if action in {"delete", "删除"}:
        with session_scope() as session:
            schedule, error = _find_schedule(session, group_id, user_id, payload)
            if error:
                return error
            schedule.enabled = False
            return f"已删除重要日程 #{schedule.id}。"

    return "用法：/重要日程 add 2026-06-20 考试；/重要日程 list；/重要日程 delete 1"


@schedule_cmd.handle()
async def handle_schedule(event: GroupMessageEvent, args: Message = CommandArg()):
    await schedule_cmd.finish(await _handle_schedule(event, args.extract_plain_text().strip()))


@add_schedule_cmd.handle()
async def handle_add_schedule(event: GroupMessageEvent, args: Message = CommandArg()):
    await add_schedule_cmd.finish(await _handle_schedule(event, f"add {args.extract_plain_text().strip()}"))


@list_schedule_cmd.handle()
async def handle_list_schedule(event: GroupMessageEvent):
    await list_schedule_cmd.finish(await _handle_schedule(event, "list"))


@delete_schedule_cmd.handle()
async def handle_delete_schedule(event: GroupMessageEvent, args: Message = CommandArg()):
    await delete_schedule_cmd.finish(await _handle_schedule(event, f"delete {args.extract_plain_text().strip()}"))
