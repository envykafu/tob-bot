from datetime import datetime, timedelta

import nonebot
from nonebot import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.config import settings
from src.db import Course, CourseAdjustment, CourseReminder, ImportantSchedule, Todo, init_db, session_scope
from src.formatting import at_user
from src.time_utils import TZ, combine_today, now_local
from src.week_utils import is_week_enabled, week_number_for


scheduler = AsyncIOScheduler(timezone=TZ)
DAY_BASED_TODO_REMIND_HOUR = 8
COURSE_REMINDER_LATE_GRACE_MINUTES = 30
IMPORTANT_SCHEDULE_REMIND_HOUR = 8


def _first_bot():
    bots = nonebot.get_bots()
    if not bots:
        return None
    return next(iter(bots.values()))


async def _send_group(group_id: str, user_id: str, text: str) -> bool:
    bot = _first_bot()
    if bot is None:
        logger.warning("Skip reminder because no OneBot connection is available.")
        return False
    try:
        await bot.send_group_msg(group_id=int(group_id), message=at_user(user_id) + " " + text)
    except Exception as exc:
        logger.warning(f"Failed to send reminder to group {group_id}: {exc}")
        return False
    return True


def _should_send_interval_reminder(todo: Todo, current) -> bool:
    if not todo.remind_every_minutes:
        return False

    interval = timedelta(minutes=todo.remind_every_minutes)
    if todo.remind_every_minutes >= 1440 and todo.remind_every_minutes % 1440 == 0:
        if current.hour < DAY_BASED_TODO_REMIND_HOUR:
            return False
        days = todo.remind_every_minutes // 1440
        last_date = todo.last_reminded_at.date() if todo.last_reminded_at else todo.created_at.date()
        if current.date() == last_date:
            return False
        return current.date() >= last_date + timedelta(days=days)

    base = todo.last_reminded_at or todo.created_at
    return current >= base + interval


async def remind_todos() -> None:
    current = now_local()
    messages: list[tuple[str, str, str, int, str]] = []
    with session_scope() as session:
        todos = session.scalars(select(Todo).where(Todo.done.is_(False))).all()
        for todo in todos:
            in_pre_due_window = False
            in_lead_window = False
            if todo.due_at:
                if todo.lead_remind_minutes:
                    lead_time = todo.due_at - timedelta(minutes=todo.lead_remind_minutes)
                    if lead_time <= current < todo.due_at:
                        in_lead_window = True
                        last_lead = todo.last_lead_reminded_at
                        if last_lead is None or last_lead < lead_time:
                            due_text = todo.due_at.strftime("%Y-%m-%d %H:%M")
                            messages.append(
                                (
                                    todo.group_id,
                                    todo.user_id,
                                    f"todo 提前提醒：#{todo.id} {todo.content}（截止 {due_text}）",
                                    todo.id,
                                    "lead",
                                )
                            )

                pre_due_start = todo.due_at - timedelta(days=1)
                if todo.created_at <= pre_due_start <= current < todo.due_at and not in_lead_window:
                    in_pre_due_window = True
                    last_pre_due = todo.last_pre_due_reminded_at
                    if last_pre_due is None or current >= last_pre_due + timedelta(hours=2):
                        due_text = todo.due_at.strftime("%Y-%m-%d %H:%M")
                        messages.append(
                            (
                                todo.group_id,
                                todo.user_id,
                                f"todo 截止前提醒：#{todo.id} {todo.content}（截止 {due_text}）",
                                todo.id,
                                "pre_due",
                            )
                        )

            should_remind = False
            if todo.due_at and current >= todo.due_at:
                if todo.last_reminded_at is None or todo.last_reminded_at < todo.due_at:
                    should_remind = True
                elif todo.remind_every_minutes:
                    next_remind = todo.last_reminded_at + timedelta(minutes=todo.remind_every_minutes)
                    should_remind = current >= next_remind
            elif todo.due_at and current < todo.due_at and todo.remind_every_minutes:
                should_remind = not in_pre_due_window and not in_lead_window and _should_send_interval_reminder(todo, current)
            elif todo.remind_every_minutes:
                should_remind = _should_send_interval_reminder(todo, current)

            if not should_remind:
                continue

            due_text = todo.due_at.strftime("%Y-%m-%d %H:%M") if todo.due_at else "未设置截止时间"
            messages.append((todo.group_id, todo.user_id, f"todo 提醒：#{todo.id} {todo.content}（{due_text}）", todo.id, "due"))

    sent_updates: list[tuple[int, str]] = []
    for group_id, user_id, text, todo_id, reminder_type in messages:
        if await _send_group(group_id, user_id, text):
            sent_updates.append((todo_id, reminder_type))
    if not sent_updates:
        return
    with session_scope() as session:
        for todo_id, reminder_type in sent_updates:
            todo = session.get(Todo, todo_id)
            if todo is None or todo.done:
                continue
            if reminder_type == "pre_due":
                todo.last_pre_due_reminded_at = current
            elif reminder_type == "lead":
                todo.last_lead_reminded_at = current
            else:
                todo.last_reminded_at = current
            todo.updated_at = current


async def remind_courses() -> None:
    current = now_local()
    date_text = current.strftime("%Y-%m-%d")
    reminder_date = current.strftime("%Y%m%d")
    weekday = current.isoweekday()
    messages: list[tuple[str, str, str, int, str]] = []
    with session_scope() as session:
        courses = session.scalars(
            select(Course).where(Course.enabled.is_(True), Course.weekday == weekday)
        ).all()
        adjustments = session.scalars(select(CourseAdjustment).where(CourseAdjustment.date == date_text)).all()
        cancelled_days = {(item.group_id, item.user_id) for item in adjustments if item.action == "cancel_day"}
        cancelled_courses = {item.course_id for item in adjustments if item.action == "cancel_course"}

        reminder_items: list[tuple[str, int, str, str, str, str, str, str, str]] = []
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
                    course.id,
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
                    item.course_id or 0,
                    item.group_id,
                    item.user_id,
                    item.name,
                    item.start_time,
                    item.end_time,
                    extra,
                    "临时",
                )
            )

        for key_prefix, course_id, group_id, user_id, name, start_time, end_time, extra, label in reminder_items:
            start_at = combine_today(start_time, current)
            remind_at = start_at - timedelta(minutes=settings.course_remind_minutes)
            late_until = start_at + timedelta(minutes=COURSE_REMINDER_LATE_GRACE_MINUTES)
            if current < remind_at or current >= late_until:
                continue

            reminder_key = f"{key_prefix}:{reminder_date}"
            exists = session.scalar(
                select(CourseReminder).where(
                    CourseReminder.reminder_key == reminder_key,
                )
            )
            if exists:
                continue

            suffix = f"（{extra}）" if extra else ""
            prefix = f"{label}上课提醒" if label else "上课提醒"
            if current >= start_at:
                prefix = f"补发{prefix}"
                lead_text = "已开始"
            else:
                lead_text = f"{settings.course_remind_minutes} 分钟后"
            messages.append(
                (
                    group_id,
                    user_id,
                    f"{prefix}：{lead_text} {name}，时间 {start_time}-{end_time}{suffix}",
                    course_id,
                    reminder_key,
                )
            )

    sent_reminders: list[tuple[int, str]] = []
    for group_id, user_id, text, course_id, reminder_key in messages:
        if await _send_group(group_id, user_id, text):
            sent_reminders.append((course_id, reminder_key))
    if not sent_reminders:
        return
    with session_scope() as session:
        for course_id, reminder_key in sent_reminders:
            exists = session.scalar(select(CourseReminder).where(CourseReminder.reminder_key == reminder_key))
            if not exists:
                session.add(CourseReminder(course_id=course_id, reminder_key=reminder_key, reminded_at=current))


async def remind_important_schedules() -> None:
    current = now_local()
    if current.hour < IMPORTANT_SCHEDULE_REMIND_HOUR:
        return
    today_text = current.strftime("%Y-%m-%d")
    messages: list[tuple[str, str, str, int]] = []
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
            if days_left == 0:
                countdown = "就是今天"
            else:
                countdown = f"还有 {days_left} 天"
            messages.append(
                (
                    schedule.group_id,
                    schedule.user_id,
                    f"重要日程倒计时：{schedule.title} {countdown}（{schedule.target_date}）",
                    schedule.id,
                )
            )

    sent_schedule_ids: list[int] = []
    for group_id, user_id, text, schedule_id in messages:
        if await _send_group(group_id, user_id, text):
            sent_schedule_ids.append(schedule_id)
    if not sent_schedule_ids:
        return
    with session_scope() as session:
        for schedule_id in sent_schedule_ids:
            schedule = session.get(ImportantSchedule, schedule_id)
            if schedule is not None and schedule.enabled:
                schedule.last_countdown_date = today_text


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
    scheduler.add_job(
        remind_important_schedules,
        "interval",
        minutes=10,
        id="catch_up_important_schedules",
        replace_existing=True,
    )
    scheduler.start()


@driver.on_shutdown
async def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
