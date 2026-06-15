import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH, override=False)


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


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8080"))
    superusers: list[str] = None
    nickname: list[str] = None
    command_start: list[str] = None

    db_path: Path = Path(os.getenv("BOT_DB_PATH", "./data/bot.db"))
    timezone: str = os.getenv("BOT_TIMEZONE", "Asia/Shanghai")
    course_remind_minutes: int = int(os.getenv("COURSE_REMIND_MINUTES", "15"))
    black_history_dir: Path = Path(os.getenv("BLACK_HISTORY_DIR", "./data/black_history"))

    ai_enabled: bool = _bool("AI_ENABLED", True)
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_model: str = os.getenv("AI_MODEL", "gpt-4o")
    ai_timeout_seconds: int = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "superusers", _json_list("SUPERUSERS", []))
        object.__setattr__(self, "nickname", _json_list("NICKNAME", ["课程助手"]))
        object.__setattr__(self, "command_start", _json_list("COMMAND_START", ["/"]))
        object.__setattr__(self, "db_path", self.db_path.expanduser())
        object.__setattr__(self, "black_history_dir", self.black_history_dir.expanduser())


settings = Settings()
