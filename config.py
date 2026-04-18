from dotenv import load_dotenv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)


def require_str(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Не найден {name} в .env")
    return value


def require_int(name: str) -> int:
    return int(require_str(name))


TOKEN = require_str("TOKEN")
GUILD_ID = require_int("GUILD_ID")

APPEALS_LOG_CHANNEL_ID = require_int("APPEALS_LOG_CHANNEL_ID")
HR_LOG_CHANNEL_ID = require_int("HR_LOG_CHANNEL_ID")
SYSTEM_LOG_CHANNEL_ID = require_int("SYSTEM_LOG_CHANNEL_ID")

SO_CATEGORY_ID = require_int("SO_CATEGORY_ID")
VSO_CATEGORY_ID = require_int("VSO_CATEGORY_ID")
ARCHIVE_CATEGORY_ID = require_int("ARCHIVE_CATEGORY_ID")

REMINDER_HOURS = int(os.getenv("REMINDER_HOURS", "48"))
PROBATION_DAYS = int(os.getenv("PROBATION_DAYS", "5"))

ROLE_LEADER = require_int("ROLE_LEADER")
ROLE_DEPUTY = require_int("ROLE_DEPUTY")
ROLE_SO_HEAD = require_int("ROLE_SO_HEAD")
ROLE_VSO_HEAD = require_int("ROLE_VSO_HEAD")
ROLE_SO = require_int("ROLE_SO")
ROLE_VSO = require_int("ROLE_VSO")
ROLE_INVESTIGATOR = require_int("ROLE_INVESTIGATOR")
ROLE_CRIMINALIST = require_int("ROLE_CRIMINALIST")
ROLE_TRAINEE = require_int("ROLE_TRAINEE")
EMPLOYEE_ROLE_ID = require_int("EMPLOYEE_ROLE_ID")

ROLE_RANK_8 = require_int("ROLE_RANK_8")
ROLE_RANK_9 = require_int("ROLE_RANK_9")

LEADERSHIP_ROLE_IDS = {
    ROLE_LEADER,
    ROLE_DEPUTY,
}

LEADER_PANEL_ROLE_IDS = {
    ROLE_RANK_8,
    ROLE_RANK_9,
}

STAFF_ROLE_IDS = {
    ROLE_LEADER,
    ROLE_DEPUTY,
    ROLE_SO_HEAD,
    ROLE_VSO_HEAD,
    ROLE_SO,
    ROLE_VSO,
    ROLE_INVESTIGATOR,
    ROLE_CRIMINALIST,
}

SO_ROLE_IDS = {
    ROLE_LEADER,
    ROLE_DEPUTY,
    ROLE_SO_HEAD,
    ROLE_SO,
    ROLE_INVESTIGATOR,
    ROLE_CRIMINALIST,
}

VSO_ROLE_IDS = {
    ROLE_LEADER,
    ROLE_DEPUTY,
    ROLE_VSO_HEAD,
    ROLE_VSO,
    ROLE_INVESTIGATOR,
}

RANK_ROLE_IDS = {
    "Младший лейтенант юстиции": require_int("ROLE_RANK_1"),
    "Лейтенант юстиции": require_int("ROLE_RANK_2"),
    "Старший лейтенант юстиции": require_int("ROLE_RANK_3"),
    "Капитан юстиции": require_int("ROLE_RANK_4"),
    "Майор юстиции": require_int("ROLE_RANK_5"),
    "Подполковник юстиции": require_int("ROLE_RANK_6"),
    "Полковник юстиции": require_int("ROLE_RANK_7"),
    "Генерал-майор юстиции": ROLE_RANK_8,
}
