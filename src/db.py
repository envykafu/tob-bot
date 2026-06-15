from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.config import settings
from src.time_utils import now_local


class Base(DeclarativeBase):
    pass


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remind_every_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_pre_due_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    teacher: Mapped[str] = mapped_column(String(64), default="")
    weeks: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class CourseReminder(Base):
    __tablename__ = "course_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    reminder_key: Mapped[str] = mapped_column(String(32), index=True)
    reminded_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class CourseAdjustment(Base):
    __tablename__ = "course_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    course_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    start_time: Mapped[str] = mapped_column(String(5), default="")
    end_time: Mapped[str] = mapped_column(String(5), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    teacher: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class BlackHistory(Base):
    __tablename__ = "black_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    content_type: Mapped[str] = mapped_column(String(16), default="image")
    content: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class ImportantSchedule(Base):
    __tablename__ = "important_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(128))
    target_date: Mapped[str] = mapped_column(String(10), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_countdown_date: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class DriftBottle(Base):
    __tablename__ = "drift_bottles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    content_type: Mapped[str] = mapped_column(String(16), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(Text, default="")
    picked_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


def make_engine():
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    migrate_db()


def migrate_db() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    statements = []
    if "courses" in table_names:
        existing = {column["name"] for column in inspector.get_columns("courses")}
        if "start_date" not in existing:
            statements.append("ALTER TABLE courses ADD COLUMN start_date VARCHAR(10) DEFAULT ''")
        if "end_date" not in existing:
            statements.append("ALTER TABLE courses ADD COLUMN end_date VARCHAR(10) DEFAULT ''")
    if "todos" in table_names:
        existing = {column["name"] for column in inspector.get_columns("todos")}
        if "start_at" not in existing:
            statements.append("ALTER TABLE todos ADD COLUMN start_at DATETIME")
        if "end_at" not in existing:
            statements.append("ALTER TABLE todos ADD COLUMN end_at DATETIME")
        if "last_pre_due_reminded_at" not in existing:
            statements.append("ALTER TABLE todos ADD COLUMN last_pre_due_reminded_at DATETIME")
    if "black_history" in table_names:
        existing = {column["name"] for column in inspector.get_columns("black_history")}
        if "content_type" not in existing:
            statements.append("ALTER TABLE black_history ADD COLUMN content_type VARCHAR(16) DEFAULT 'image'")
        if "content" not in existing:
            statements.append("ALTER TABLE black_history ADD COLUMN content TEXT DEFAULT ''")
        if "file_path" not in existing:
            statements.append("ALTER TABLE black_history ADD COLUMN file_path TEXT DEFAULT ''")
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
