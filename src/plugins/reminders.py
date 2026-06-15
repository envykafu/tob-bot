from datetime import datetime, timedelta

import nonebot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.config import settings
from src.db import Course, CourseAdjustment, CourseReminder, ImportantSchedule, Todo, init_db, session_scope
from src.formatting import at_user
from src.time_utils import TZ, combine_today, now_local
from src.week_utils import is_week_enabled, week_number_for


scheduler = AsyncIOScheduler(timezone=TZ)


def _first_bot():
    bots = nonebot.get_bots()
    if not bots:
        return None
    return next(iter(bots.values()))


async def _send_group(group_id: str, user_id: str, text: str) -> None:
    bot = _first_bot()
    if bot is None:
        return
    await bot.send_group_msg(group_id=int(group_id), message=at_user(user_id) + " " + text)


async def remind_todos() -> None:
    current = now_local()
    messages: list[tuple[str, str, str]] = []
    with session_scope() as session:
        todos = session.scalars(select(Todo).where(Todo.done.is_(False))).all()
        for todo in todos:
            if todo.due_at:
                pre_due_start = todo.due_at - timedelta(days=1)
                if pre_due_start <= current < todo.due_at:
                    last_pre_due = todo.last_pre_due_reminded_at
                    if last_pre_due is None or current >= last_pre_due + timedelta(hours=2):
                        todo.last_pre_due_reminded_at = current
                        todo.updated_at = current
                        due_text = todo.due_at.strftime("%Y-%m-%d %H:%M")
                        messages.append(
                            (
                                todo.group_id,
                                todo.user_id,
                                f"todo 截止前提醒：#{todo.id} {todo.content}（截止 {due_text}）",
                            )
                        )

            should_remind = False
            if todo.due_at and current >= todo.due_at:
                if todo.last_reminded_at is None:
                    should_remind = True
                elif todo.remind_every_minutes:
                    next_remind = todo.last_reminded_at + timedelta(minutes=todo.remind_every_minutes)
                    should_remind = current >= next_remind
            elif todo.remind_every_minutes:
                base = todo.last_reminded_at or todo.due_at or todo.created_at
                should_remind = current >= base + timedelta(minutes=todo.remind_every_minutes)

            if not should_remind:
                continue

            todo.last_reminded_at = current
            todo.updated_at = current
            due_text = todo.due_at.strftime("%Y-%m-%d %H:%M") if todo.due_at else "未设置截止时间"
            messages.append((todo.group_id, todo.user_id, f"todo 提醒：#{todo.id} {todo.content}（{due_text}）"))

    for group_id, user_id, text in messages:
        await _send_group(group_id, user_id, text)


async def remind_courses() -> None:
    current = now_local()
    date_text = current.strftime("%Y-%m-%d")
    reminder_date = current.strftime("%Y%m%d")
    weekday = current.isoweekday()
    messages: list[tuple[str, str, str]] = []
    with session_scope() as session:
        courses = session.scalars(
            select(Course).where(Course.enabled.is_(True), Course.weekday == weekday)
        ).all()
        adjustments = session.scalars(select(CourseAdjustment).where(CourseAdjustment.date == date_text)).all()
        cancelled_days = {(item.group_id, item.user_id) for item in adjustments if item.action == "cancel_day"}
        cancelled_courses = {item.course_id for item in adjustments if item.action == "cancel_course"}

        reminder_items: list[tuple[str, str, str, str, str, str, str, str]] = []
        for course in courses:
            if (course.group_id, course.user_id) in cancelled_days:
                continue
            if course.id in cancelled_courses:
                continue
            if course.start_date and date_text < course.start_date:
                continue
            if course.end_date and date_text > course.end_date:
                continue
            week_number = week_number_for(date_text, course.start_date)
            if not is_week_enabled(course.weeks, week_number):
                continue
            extra = " ".join(part for part in [course.location, course.teacher, course.weeks] if part)
            reminder_items.append(
                (
                    f"course:{course.id}",
                    course.group_id,
                    course.user_id,
                    course.name,
                    course.start_time,
                    course.end_time,
                    extra,
                    "",
                )
            )

        for item in adjustments:
            if item.action != "add_course":
                continue
            extra = " ".join(part for part in [item.location, item.teacher, item.note] if part)
            reminder_items.append(
                (
                    f"adjustment:{item.id}",
                    item.group_id,
                    item.user_id,
                    item.name,
                    item.start_time,
                    item.end_time,
                    extra,
                    "临时",
                )
            )

        for key_prefix, group_id, user_id, name, start_time, end_time, extra, label in reminder_items:
            start_at = combine_today(start_time, current)
            remind_at = start_at - timedelta(minutes=settings.course_remind_minutes)
            if current < remind_at or current >= start_at:
                continue

            reminder_key = f"{key_prefix}:{reminder_date}"
            exists = session.scalar(
                select(CourseReminder).where(
                    CourseReminder.course_id == 0,
                    CourseReminder.reminder_key == reminder_key,
                )
            )
            if exists:
                continue

            session.add(CourseReminder(course_id=0, reminder_key=reminder_key, reminded_at=current))
            suffix = f"（{extra}）" if extra else ""
            prefix = f"{label}上课提醒" if label else "上课提醒"
            messages.append(
                (
                    group_id,
                    user_id,
                    f"{prefix}：{settings.course_remind_minutes} 分钟后 {name} 开始，时间 {start_time}-{end_time}{suffix}",
                )
            )

    for group_id, user_id, text in messages:
        await _send_group(group_id, user_id, text)


async def remind_important_schedules() -> None:
    current = now_local()
    today_text = current.strftime("%Y-%m-%d")
    messages: list[tuple[str, str, str]] = []
    with session_scope() as session:
        schedules = session.scalars(
            select(ImportantSchedule).where(ImportantSchedule.enabled.is_(True))
        ).all()
        for schedule in schedules:
            if schedule.last_countdown_date == today_text:
                continue
            try:
                target = datetime.strptime(schedule.target_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            days_left = (target - current.date()).days
            if days_left < 0:
                schedule.enabled = False
                continue
            schedule.last_countdown_date = today_text
            if days_left == 0:
                countdown = "就是今天"
            else:
                countdown = f"还有 {days_left} 天"
            messages.append(
                (
                    schedule.group_id,
                    schedule.user_id,
                    f"重要日程倒计时：{schedule.title} {countdown}（{schedule.target_date}）",
                )
            )

    for group_id, user_id, text in messages:
        await _send_group(group_id, user_id, text)


driver = nonebot.get_driver()


@driver.on_startup
async def start_scheduler() -> None:
    init_db()
    scheduler.add_job(remind_todos, "interval", minutes=1, id="remind_todos", replace_existing=True)
    scheduler.add_job(remind_courses, "interval", minutes=1, id="remind_courses", replace_existing=True)
    scheduler.add_job(
        remind_important_schedules,
        "cron",
        hour=8,
        minute=0,
        id="remind_important_schedules",
        replace_existing=True,
    )
    scheduler.start()


@driver.on_shutdown
async def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
