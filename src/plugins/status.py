import os
import platform
from datetime import timedelta
from pathlib import Path

import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from sqlalchemy import func, select

from src.config import settings
from src.db import (
    AIConversation,
    BlackHistory,
    Course,
    DriftBottle,
    ImportantSchedule,
    Todo,
    init_db,
    session_scope,
)
from src.time_utils import now_local


status_cmd = on_command("status", aliases={"状态"}, priority=10, block=True)
driver = nonebot.get_driver()
STARTED_AT = now_local()


def _is_admin(user_id: int | str) -> bool:
    return str(user_id) in set(settings.superusers)


def _format_uptime() -> str:
    delta = now_local() - STARTED_AT
    seconds = max(0, int(delta.total_seconds()))
    uptime = timedelta(seconds=seconds)
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    parts.append(f"{minutes}分钟")
    return "".join(parts)


def _db_size() -> str:
    path = Path(settings.db_path)
    if not path.exists():
        return "未创建"
    size = path.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024:.1f} KB"


def _count(session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(session.scalar(statement) or 0)


def _database_summary() -> list[str]:
    init_db()
    with session_scope() as session:
        open_todos = _count(session, Todo, Todo.done.is_(False))
        done_todos = _count(session, Todo, Todo.done.is_(True))
        courses = _count(session, Course, Course.enabled.is_(True))
        schedules = _count(session, ImportantSchedule, ImportantSchedule.enabled.is_(True))
        black_history = _count(session, BlackHistory)
        bottles = _count(session, DriftBottle)
        ai_contexts = _count(session, AIConversation)
    return [
        f"Todo：未完成 {open_todos}，已完成 {done_todos}",
        f"课程：启用 {courses}",
        f"重要日程：启用 {schedules}",
        f"黑历史：{black_history}",
        f"漂流瓶：{bottles}",
        f"AI上下文：{ai_contexts}",
        f"数据库：{settings.db_path}（{_db_size()}）",
    ]


def _basic_status_lines(bot: Bot) -> list[str]:
    bot_ids = sorted(str(bot_id) for bot_id in driver.bots.keys())
    return [
        "Bot 状态：正常运行",
        f"账号：{bot.self_id}",
        f"OneBot连接数：{len(driver.bots)}（{', '.join(bot_ids) or '无'}）",
        f"运行时长：{_format_uptime()}",
        f"启动时间：{STARTED_AT:%Y-%m-%d %H:%M:%S}",
    ]


def _status_text(bot: Bot, detail: bool = True) -> str:
    lines = _basic_status_lines(bot)
    if not detail:
        return "\n".join(lines)
    ai_key_status = "已配置" if settings.ai_api_key else "未配置"
    lines = [
        *lines,
        f"进程：pid {os.getpid()}，Python {platform.python_version()}",
        f"监听：{settings.host}:{settings.port}",
        f"管理员数：{len(settings.superusers)}",
        f"AI：{'开启' if settings.ai_enabled else '关闭'}，Key {ai_key_status}，模型 {settings.ai_model}",
        f"AI接口：{settings.ai_base_url}",
        "",
        "数据：",
        *_database_summary(),
    ]
    return "\n".join(lines)


@status_cmd.handle()
async def handle_status(bot: Bot, event: MessageEvent):
    if not _is_admin(event.user_id):
        await status_cmd.finish("你没有权限使用 /status。")
    await status_cmd.finish(_status_text(bot, detail=not isinstance(event, GroupMessageEvent)))
