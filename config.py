import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset
    group_id: int | None
    db_path: str
    tz: ZoneInfo
    send_hour: int
    send_minute: int
    catchup_on_start: bool


def _ids(raw: str) -> frozenset:
    return frozenset(int(x) for x in raw.replace(";", ",").split(",") if x.strip())


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    admins = _ids(os.getenv("ADMIN_IDS", ""))
    if not admins:
        raise RuntimeError("ADMIN_IDS is not set")
    group = os.getenv("GROUP_ID", "").strip()
    return Config(
        bot_token=token,
        admin_ids=admins,
        group_id=int(group) if group else None,
        db_path=os.getenv("DB_PATH", "data/duty.db"),
        tz=ZoneInfo("Asia/Tashkent"),
        send_hour=int(os.getenv("SEND_HOUR", "20")),
        send_minute=int(os.getenv("SEND_MINUTE", "0")),
        catchup_on_start=os.getenv("CATCHUP_ON_START", "true").lower() in ("1", "true", "yes"),
    )
