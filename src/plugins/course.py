import csv
from io import StringIO

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg
from sqlalchemy import delete, select

from src.db import Course, CourseAdjustment, init_db, session_scope
from src.time_utils import parse_date_or_today, parse_hhmm
from src.week_utils import is_week_enabled


course_cmd = on_command("course", aliases={"课表"}, priority=20, block=True)
add_course_cmd = on_command("添加课程", priority=20, block=True)
delete_course_cmd = on_command("删除课程", aliases={"取消课程"}, priority=20, block=True)
move_course_cmd = on_command("移动课程", priority=20, block=True)
list_course_cmd = on_command("查看课程", aliases={"课程表"}, priority=20, block=True)
sample_course_cmd = on_command("课程模板", priority=20, block=True)
import_course_cmd = on_command("导入课程表", priority=20, block=True)

REQUIRED_FIELDS = {"course_name", "weekday", "start_time", "end_time", "start_date", "end_date"}


def _validate_row(row: dict[str, str], line_no: int) -> tuple[bool, str]:
    missing = [field for field in REQUIRED_FIELDS if not row.get(field)]
    if missing:
        return False, f"第 {line_no} 行缺少字段：{', '.join(missing)}"
    try:
        weekday = int(row["weekday"])
    except ValueError:
        return False, f"第 {line_no} 行 weekday 必须是 1-7。"
    if weekday < 1 or weekday > 7:
        return False, f"第 {line_no} 行 weekday 必须是 1-7。"
    try:
        parse_hhmm(row["start_time"])
        parse_hhmm(row["end_time"])
    except ValueError:
        return False, f"第 {line_no} 行时间必须是 HH:MM，例如 08:00。"
    if not parse_date_or_today(row["start_date"]) or not parse_date_or_today(row["end_date"]):
        return False, f"第 {line_no} 行 start_date/end_date 必须是日期，例如 2026-09-01。"
    weeks = row.get("weeks", "").strip()
    if weeks:
        # week 1 is enough to reject only completely malformed rules.
        is_week_enabled(weeks, 1)
    return True, ""


def _find_course(session, group_id: str, user_id: str, target: str):
    target = target.strip()
    if target.isdigit():
        course = session.scalar(
            select(Course).where(Course.id == int(target), Course.group_id == group_id, Course.user_id == user_id)
        )
        return course, None
    courses = session.scalars(
        select(Course).where(
            Course.group_id == group_id,
            Course.user_id == user_id,
            Course.enabled.is_(True),
            Course.name == target,
        )
    ).all()
    if len(courses) == 1:
        return courses[0], None
    if len(courses) > 1:
        ids = ", ".join(f"#{course.id}" for course in courses)
        return None, f"有多个同名课程：{ids}，请使用课程 ID。"
    return None, "没有找到这门课程。"


async def _handle_course(event: GroupMessageEvent, raw: str):
    init_db()
    if not raw:
        return "用法：/添加课程 日期 时间段 课程名 地点；/删除课程 日期 课程名；/移动课程 课程名 原日期 新日期 时间段 地点"

    action, _, payload = raw.partition(" ")
    action = action.lower()
    group_id = str(event.group_id)
    user_id = str(event.user_id)

    if action in {"sample", "模板"}:
        return "\n".join(
            [
                "CSV 示例：",
                "course_name,weekday,start_time,end_time,start_date,end_date,location,teacher,weeks",
                "高等数学,1,08:00,09:40,2026-09-01,2027-01-10,A101,张老师,1-16",
                "大学英语,3,14:00,15:40,2026-09-01,2027-01-10,B203,李老师,1-16单周",
                "体育,5,10:00,11:40,2026-09-01,2027-01-10,操场,王老师,2-16双周",
            ]
        )

    if action in {"import", "导入"}:
        csv_text = payload.strip()
        if not csv_text:
            return "请在 /导入课程表 后粘贴 CSV 内容。"
        reader = csv.DictReader(StringIO(csv_text))
        if not reader.fieldnames:
            return "CSV 缺少表头。"
        normalized = {field.strip().lstrip("\ufeff") for field in reader.fieldnames if field}
        if not REQUIRED_FIELDS.issubset(normalized):
            return "CSV 表头至少需要：course_name,weekday,start_time,end_time,start_date,end_date"

        imported: list[Course] = []
        for idx, row in enumerate(reader, start=2):
            clean = {str(k).strip().lstrip("\ufeff"): (v or "").strip() for k, v in row.items() if k is not None}
            ok, error = _validate_row(clean, idx)
            if not ok:
                return error
            imported.append(
                Course(
                    group_id=group_id,
                    user_id=user_id,
                    name=clean["course_name"],
                    weekday=int(clean["weekday"]),
                    start_time=clean["start_time"],
                    end_time=clean["end_time"],
                    start_date=parse_date_or_today(clean["start_date"]) or "",
                    end_date=parse_date_or_today(clean["end_date"]) or "",
                    location=clean.get("location", ""),
                    teacher=clean.get("teacher", ""),
                    weeks=clean.get("weeks", ""),
                )
            )
        if not imported:
            return "CSV 没有课程数据。"
        with session_scope() as session:
            session.execute(delete(Course).where(Course.group_id == group_id, Course.user_id == user_id))
            session.add_all(imported)
        return f"已导入 {len(imported)} 门课程，旧课表已替换。"

    if action in {"list", "查看"}:
        with session_scope() as session:
            courses = session.scalars(
                select(Course)
                .where(Course.group_id == group_id, Course.user_id == user_id, Course.enabled.is_(True))
                .order_by(Course.weekday, Course.start_time, Course.id)
            ).all()
        if not courses:
            return "你还没有导入课程表。"
        lines = ["你的课程表："]
        for course in courses:
            date_range = f"{course.start_date}~{course.end_date}" if course.start_date and course.end_date else ""
            extra = " ".join(part for part in [date_range, course.location, course.teacher, course.weeks] if part)
            suffix = f"（{extra}）" if extra else ""
            lines.append(f"#{course.id} 周{course.weekday} {course.start_time}-{course.end_time} {course.name}{suffix}")
        return "\n".join(lines)

    if action in {"clear", "清空"}:
        with session_scope() as session:
            session.execute(delete(Course).where(Course.group_id == group_id, Course.user_id == user_id))
        return "已清空你的课程表。"

    if action in {"cancel", "delete", "删除", "取消"}:
        parts = payload.split()
        if len(parts) < 2:
            return "用法：/删除课程 2026-10-01 课程ID或课程名；取消整天用 /删除课程 2026-10-01 all"
        date = parse_date_or_today(parts[0])
        if not date:
            return "日期格式不正确，例如 2026-10-01、明天。"
        target = " ".join(parts[1:])
        if target.lower() in {"all", "全部", "全天"}:
            with session_scope() as session:
                session.add(CourseAdjustment(group_id=group_id, user_id=user_id, action="cancel_day", date=date))
            return f"已取消 {date} 当天你的所有课程。"
        with session_scope() as session:
            course, error = _find_course(session, group_id, user_id, target)
            if error:
                return error
            session.add(
                CourseAdjustment(
                    group_id=group_id,
                    user_id=user_id,
                    action="cancel_course",
                    date=date,
                    course_id=course.id,
                    name=course.name,
                )
            )
        return f"已取消 {date} 的 {course.name}。"

    if action in {"add", "添加"}:
        parts = payload.split()
        if len(parts) < 4:
            return "用法：/添加课程 2026-10-08 08:00-09:40 课程名 地点"
        date = parse_date_or_today(parts[0])
        if not date:
            return "日期格式不正确，例如 2026-10-08、明天。"
        time_range = parts[1]
        if "-" not in time_range:
            return "时间段格式应为 08:00-09:40。"
        start_time, end_time = [item.strip() for item in time_range.split("-", 1)]
        try:
            parse_hhmm(start_time)
            parse_hhmm(end_time)
        except ValueError:
            return "时间格式必须是 HH:MM，例如 08:00。"
        name = parts[2]
        location = " ".join(parts[3:])
        with session_scope() as session:
            session.add(
                CourseAdjustment(
                    group_id=group_id,
                    user_id=user_id,
                    action="add_course",
                    date=date,
                    name=name,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                )
            )
        return f"已添加临时课程：{date} {start_time}-{end_time} {name} {location}"

    if action in {"move", "移动"}:
        parts = payload.split()
        if len(parts) < 4:
            return "用法：/移动课程 课程ID或课程名 原日期 新日期 10:00-11:40 地点"
        target = parts[0]
        from_date = parse_date_or_today(parts[1])
        maybe_to_date = parse_date_or_today(parts[2]) if len(parts) >= 5 else None
        if maybe_to_date:
            to_date = maybe_to_date
            time_range = parts[3]
            location = " ".join(parts[4:])
        else:
            to_date = from_date
            time_range = parts[2]
            location = " ".join(parts[3:])
        if not from_date or not to_date:
            return "日期格式不正确，例如 2026-10-08、明天。"
        if "-" not in time_range:
            return "时间段格式应为 10:00-11:40。"
        start_time, end_time = [item.strip() for item in time_range.split("-", 1)]
        try:
            parse_hhmm(start_time)
            parse_hhmm(end_time)
        except ValueError:
            return "时间格式必须是 HH:MM，例如 10:00。"
        with session_scope() as session:
            course, error = _find_course(session, group_id, user_id, target)
            if error:
                return error
            session.add(
                CourseAdjustment(
                    group_id=group_id,
                    user_id=user_id,
                    action="cancel_course",
                    date=from_date,
                    course_id=course.id,
                    name=course.name,
                )
            )
            session.add(
                CourseAdjustment(
                    group_id=group_id,
                    user_id=user_id,
                    action="add_course",
                    date=to_date,
                    course_id=course.id,
                    name=course.name,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                )
            )
        return f"已移动课程：{course.name} {from_date} -> {to_date} {start_time}-{end_time} {location}"

    return "未知课程表命令。可用：/课程模板 /导入课程表 /查看课程 /添加课程 /删除课程 /移动课程"


@course_cmd.handle()
async def handle_course(event: GroupMessageEvent, args: Message = CommandArg()):
    await course_cmd.finish(await _handle_course(event, args.extract_plain_text().strip()))


@add_course_cmd.handle()
async def handle_add_course(event: GroupMessageEvent, args: Message = CommandArg()):
    await add_course_cmd.finish(await _handle_course(event, f"add {args.extract_plain_text().strip()}"))


@delete_course_cmd.handle()
async def handle_delete_course(event: GroupMessageEvent, args: Message = CommandArg()):
    await delete_course_cmd.finish(await _handle_course(event, f"cancel {args.extract_plain_text().strip()}"))


@move_course_cmd.handle()
async def handle_move_course(event: GroupMessageEvent, args: Message = CommandArg()):
    await move_course_cmd.finish(await _handle_course(event, f"move {args.extract_plain_text().strip()}"))


@list_course_cmd.handle()
async def handle_list_course(event: GroupMessageEvent):
    await list_course_cmd.finish(await _handle_course(event, "list"))


@sample_course_cmd.handle()
async def handle_sample_course(event: GroupMessageEvent):
    await sample_course_cmd.finish(await _handle_course(event, "sample"))


@import_course_cmd.handle()
async def handle_import_course(event: GroupMessageEvent, args: Message = CommandArg()):
    await import_course_cmd.finish(await _handle_course(event, f"import {args.extract_plain_text().strip()}"))
