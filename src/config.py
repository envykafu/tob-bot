import json
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH, override=False)


class ConfigError(RuntimeError):
    pass


def _json_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError(f"配置错误：{name} 必须是整数，当前值是 {raw!r}") from exc
    if min_value is not None and value < min_value:
        raise ConfigError(f"配置错误：{name} 必须大于等于 {min_value}，当前值是 {value}")
    if max_value is not None and value > max_value:
        raise ConfigError(f"配置错误：{name} 必须小于等于 {max_value}，当前值是 {value}")
    return value


def _timezone(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"配置错误：{name} 不是有效时区，当前值是 {value!r}") from exc
    return value


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8080, min_value=1, max_value=65535)
    superusers: list[str] = None
    nickname: list[str] = None
    command_start: list[str] = None

    db_path: Path = Path(os.getenv("BOT_DB_PATH", "./data/bot.db"))
    timezone: str = _timezone("BOT_TIMEZONE", "Asia/Shanghai")
    course_remind_minutes: int = _int("COURSE_REMIND_MINUTES", 15, min_value=1)
    black_history_dir: Path = Path(os.getenv("BLACK_HISTORY_DIR", "./data/black_history"))
    black_history_max_per_group: int = _int("BLACK_HISTORY_MAX_PER_GROUP", 500, min_value=1)
    black_history_max_per_user: int = _int("BLACK_HISTORY_MAX_PER_USER", 100, min_value=1)

    ai_enabled: bool = _bool("AI_ENABLED", True)
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "gpt-4o")
    ai_timeout_seconds: int = _int("AI_TIMEOUT_SECONDS", 30, min_value=1)

    def __post_init__(self) -> None:
        object.__setattr__(self, "superusers", _json_list("SUPERUSERS", []))
        object.__setattr__(self, "nickname", _json_list("NICKNAME", ["课程助手"]))
        object.__setattr__(self, "command_start", _json_list("COMMAND_START", ["/"]))
        object.__setattr__(self, "db_path", self.db_path.expanduser())
        object.__setattr__(self, "black_history_dir", self.black_history_dir.expanduser())


settings = Settings()
