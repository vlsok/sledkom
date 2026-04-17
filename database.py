import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
DB_PATH = DATA_DIR / "bot.db"


def now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def backup_database() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bot_backup_{timestamp}.db"

    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_path)

    return str(backup_path)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            appeal_type TEXT NOT NULL,
            fio TEXT NOT NULL,
            contact TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Принято',
            priority TEXT NOT NULL DEFAULT 'Обычный',
            department TEXT,
            assigned_to INTEGER,
            accepted_by INTEGER,
            accepted_by_name TEXT,
            clarification_requested INTEGER NOT NULL DEFAULT 0,
            clarification_text TEXT,
            citizen_reply_text TEXT,
            citizen_reply_at TEXT,
            resolution_text TEXT,
            archive_flag INTEGER NOT NULL DEFAULT 0,
            log_message_id INTEGER,
            work_channel_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            closed_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appeal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appeal_number TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS hr_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            fio TEXT NOT NULL,
            age TEXT NOT NULL,
            experience TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            log_message_id INTEGER,
            processed_by INTEGER,
            processed_by_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id INTEGER NOT NULL UNIQUE,
            fio TEXT NOT NULL,
            department TEXT NOT NULL,
            position TEXT NOT NULL,
            rank_name TEXT NOT NULL,
            status TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            probation_until TEXT,
            cases_count INTEGER NOT NULL DEFAULT 0,
            closed_cases_count INTEGER NOT NULL DEFAULT 0,
            warnings_count INTEGER NOT NULL DEFAULT 0,
            promotions_count INTEGER NOT NULL DEFAULT 0,
            rewards_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS discipline_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL UNIQUE,
            discord_id INTEGER NOT NULL,
            fio TEXT NOT NULL,
            action_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            issued_by INTEGER NOT NULL,
            issued_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()


def generate_number(prefix: str, table: str, year: int | None = None) -> str:
    if year is None:
        year = datetime.now().year

    with get_connection() as conn:
        cursor = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE number LIKE ?",
            (f"{prefix}/{year}/%",)
        )
        count = cursor.fetchone()["count"] + 1

    return f"{prefix}/{year}/{count:03d}"


def generate_appeal_number() -> str:
    return generate_number("СК-ЛО", "appeals")


def generate_hr_number() -> str:
    return generate_number("ОК-ЛО", "hr_requests")


def generate_discipline_number() -> str:
    return generate_number("ДИС-ЛО", "discipline_records")


def add_appeal_history(
    appeal_number: str,
    action: str,
    actor_id: Optional[int] = None,
    actor_name: Optional[str] = None,
    details: Optional[str] = None
) -> None:
    with get_connection() as conn:
        conn.execute("""
        INSERT INTO appeal_history (
            appeal_number, action, actor_id, actor_name, details, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            appeal_number,
            action,
            actor_id,
            actor_name,
            details,
            now_str()
        ))
        conn.commit()


def determine_department(appeal_type: str, description: str) -> str:
    text = f"{appeal_type} {description}".lower()

    military_words = [
        "военный", "всо", "воинская часть", "армия",
        "военнослужащ", "контрактник", "солдат", "офицер"
    ]

    if any(word in text for word in military_words):
        return "ВСО"

    return "СО"


def determine_priority(description: str) -> str:
    text = description.lower()

    if any(word in text for word in ["срочно", "угроза", "убийств", "террор", "взрыв"]):
        return "Высокий"

    if any(word in text for word in ["проверка", "жалоба", "заявление"]):
        return "Обычный"

    return "Низкий"


def create_appeal(
    user_id: int,
    username: str,
    appeal_type: str,
    fio: str,
    contact: str,
    description: str
) -> dict:
    number = generate_appeal_number()
    department = determine_department(appeal_type, description)
    priority = determine_priority(description)
    created_at = now_str()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO appeals (
            number, user_id, username, appeal_type, fio, contact, description,
            status, priority, department, assigned_to, accepted_by, accepted_by_name,
            clarification_requested, clarification_text, citizen_reply_text, citizen_reply_at,
            resolution_text, archive_flag, log_message_id, work_channel_id, created_at, updated_at, closed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            number,
            user_id,
            username,
            appeal_type,
            fio,
            contact,
            description,
            "Принято",
            priority,
            department,
            None,
            None,
            None,
            0,
            None,
            None,
            None,
            None,
            0,
            None,
            None,
            created_at,
            created_at,
            None
        ))
        conn.commit()

    add_appeal_history(
        number,
        "Создано обращение",
        user_id,
        username,
        f"Тип: {appeal_type} / Приоритет: {priority}"
    )
    return get_appeal_by_number(number)


def get_appeal_by_number(number: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM appeals WHERE number = ?",
            (number,)
        ).fetchone()
        return dict(row) if row else None


def get_recent_appeals(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM appeals ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_appeal_history(number: str, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
        SELECT * FROM appeal_history
        WHERE appeal_number = ?
        ORDER BY id DESC
        LIMIT ?
        """, (number, limit)).fetchall()
        return [dict(row) for row in rows]


def get_active_appeals(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
        SELECT * FROM appeals
        WHERE archive_flag = 0
        ORDER BY id DESC
        LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]


def count_appeals_by_status(status: str) -> int:
    with get_connection() as conn:
        row = conn.execute("""
        SELECT COUNT(*) AS count
        FROM appeals
        WHERE status = ? AND archive_flag = 0
        """, (status,)).fetchone()
        return row["count"]


def count_hr_by_status(status: str) -> int:
    with get_connection() as conn:
        row = conn.execute("""
        SELECT COUNT(*) AS count
        FROM hr_requests
        WHERE status = ?
        """, (status,)).fetchone()
        return row["count"]


def set_appeal_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET log_message_id = ?, updated_at = ?
        WHERE number = ?
        """, (message_id, now_str(), number))
        conn.commit()


def set_appeal_work_channel(
    number: str,
    channel_id: int,
    department: str,
    accepted_by: int,
    accepted_by_name: str
) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET status = ?, work_channel_id = ?, department = ?, accepted_by = ?, accepted_by_name = ?, updated_at = ?
        WHERE number = ?
        """, (
            "В работе",
            channel_id,
            department,
            accepted_by,
            accepted_by_name,
            now_str(),
            number
        ))
        conn.commit()


def set_appeal_assigned_to(number: str, assigned_to: int) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET assigned_to = ?, updated_at = ?
        WHERE number = ?
        """, (assigned_to, now_str(), number))
        conn.commit()

    with get_connection() as conn:
        conn.execute("""
        UPDATE employees
        SET cases_count = cases_count + 1
        WHERE discord_id = ?
        """, (assigned_to,))
        conn.commit()


def set_appeal_clarification(number: str, text: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET status = ?, clarification_requested = 1, clarification_text = ?, updated_at = ?
        WHERE number = ?
        """, (
            "Требует уточнения",
            text,
            now_str(),
            number
        ))
        conn.commit()

    add_appeal_history(number, "Запрошено уточнение", actor_id, actor_name, text)


def set_citizen_reply(number: str, reply_text: str, user_id: int, username: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET citizen_reply_text = ?, citizen_reply_at = ?, updated_at = ?, status = ?
        WHERE number = ?
        """, (
            reply_text,
            now_str(),
            now_str(),
            "В работе",
            number
        ))
        conn.commit()

    add_appeal_history(number, "Поступил ответ на уточнение", user_id, username, reply_text)


def close_appeal(
    number: str,
    status: str,
    resolution_text: str,
    actor_id: int,
    actor_name: str
) -> None:
    appeal = get_appeal_by_number(number)

    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET status = ?, resolution_text = ?, updated_at = ?, closed_at = ?
        WHERE number = ?
        """, (
            status,
            resolution_text,
            now_str(),
            now_str(),
            number
        ))

        if appeal and appeal.get("assigned_to"):
            conn.execute("""
            UPDATE employees
            SET closed_cases_count = closed_cases_count + 1
            WHERE discord_id = ?
            """, (appeal["assigned_to"],))

        conn.commit()

    add_appeal_history(number, f"Обращение {status.lower()}", actor_id, actor_name, resolution_text)


def archive_appeal(number: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE appeals
        SET status = ?, archive_flag = 1, updated_at = ?, closed_at = ?
        WHERE number = ?
        """, (
            "Архив",
            now_str(),
            now_str(),
            number
        ))
        conn.commit()

    add_appeal_history(number, "Обращение архивировано", actor_id, actor_name, "Карточка отправлена в архив")


def create_hr_request(
    user_id: int,
    username: str,
    fio: str,
    age: str,
    experience: str,
    reason: str
) -> dict:
    number = generate_hr_number()
    created_at = now_str()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO hr_requests (
            number, user_id, username, fio, age, experience, reason,
            status, log_message_id, processed_by, processed_by_name, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            number,
            user_id,
            username,
            fio,
            age,
            experience,
            reason,
            "На рассмотрении",
            None,
            None,
            None,
            created_at,
            created_at
        ))
        conn.commit()

    return get_hr_request_by_number(number)


def get_hr_request_by_number(number: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM hr_requests WHERE number = ?",
            (number,)
        ).fetchone()
        return dict(row) if row else None


def get_recent_hr(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM hr_requests ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def set_hr_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE hr_requests
        SET log_message_id = ?, updated_at = ?
        WHERE number = ?
        """, (message_id, now_str(), number))
        conn.commit()


def update_hr_status(number: str, status: str, processed_by: int, processed_by_name: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE hr_requests
        SET status = ?, processed_by = ?, processed_by_name = ?, updated_at = ?
        WHERE number = ?
        """, (
            status,
            processed_by,
            processed_by_name,
            now_str(),
            number
        ))
        conn.commit()


def create_employee(
    discord_id: int,
    fio: str,
    department: str = "СО",
    position: str = "Стажёр",
    rank_name: str = "Младший лейтенант юстиции",
    probation_days: int = 5
) -> dict:
    joined_at = now_str()
    probation_until = (datetime.now() + timedelta(days=probation_days)).strftime("%d.%m.%Y %H:%M:%S")

    with get_connection() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO employees (
            discord_id, fio, department, position, rank_name, status,
            joined_at, probation_until, cases_count, closed_cases_count,
            warnings_count, promotions_count, rewards_count, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            discord_id,
            fio,
            department,
            position,
            rank_name,
            "Испытательный срок",
            joined_at,
            probation_until,
            0,
            0,
            0,
            0,
            0,
            None
        ))
        conn.commit()

    return get_employee_by_discord_id(discord_id)


def upsert_employee_from_web(
    discord_id: int,
    fio: str,
    department: str,
    position: str,
    rank_name: str,
    status: str,
    notes: str = ""
) -> dict:
    existing = get_employee_by_discord_id(discord_id)
    joined_at = existing["joined_at"] if existing else now_str()
    probation_until = existing["probation_until"] if existing else None
    cases_count = existing["cases_count"] if existing else 0
    closed_cases_count = existing["closed_cases_count"] if existing else 0
    warnings_count = existing["warnings_count"] if existing else 0
    promotions_count = existing["promotions_count"] if existing else 0
    rewards_count = existing["rewards_count"] if existing else 0

    with get_connection() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO employees (
            discord_id, fio, department, position, rank_name, status,
            joined_at, probation_until, cases_count, closed_cases_count,
            warnings_count, promotions_count, rewards_count, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            discord_id,
            fio,
            department,
            position,
            rank_name,
            status,
            joined_at,
            probation_until,
            cases_count,
            closed_cases_count,
            warnings_count,
            promotions_count,
            rewards_count,
            notes
        ))
        conn.commit()

    return get_employee_by_discord_id(discord_id)


def get_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE discord_id = ?",
            (discord_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_employees() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM employees ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def search_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    return get_employee_by_discord_id(discord_id)


def update_employee_status(discord_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE employees
        SET status = ?
        WHERE discord_id = ?
        """, (status, discord_id))
        conn.commit()


def update_employee_rank(discord_id: int, rank_name: str) -> None:
    with get_connection() as conn:
        conn.execute("""
        UPDATE employees
        SET rank_name = ?
        WHERE discord_id = ?
        """, (rank_name, discord_id))
        conn.commit()


def extend_probation(discord_id: int, days: int) -> dict | None:
    employee = get_employee_by_discord_id(discord_id)
    if not employee:
        return None

    base_dt = datetime.strptime(employee["probation_until"], "%d.%m.%Y %H:%M:%S") if employee.get("probation_until") else datetime.now()
    new_dt = base_dt + timedelta(days=days)

    with get_connection() as conn:
        conn.execute("""
        UPDATE employees
        SET probation_until = ?
        WHERE discord_id = ?
        """, (new_dt.strftime("%d.%m.%Y %H:%M:%S"), discord_id))
        conn.commit()

    return get_employee_by_discord_id(discord_id)


def add_discipline_record(
    discord_id: int,
    fio: str,
    action_type: str,
    reason: str,
    issued_by: int,
    issued_by_name: str
) -> dict:
    number = generate_discipline_number()
    created_at = now_str()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO discipline_records (
            number, discord_id, fio, action_type, reason, issued_by, issued_by_name, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            number,
            discord_id,
            fio,
            action_type,
            reason,
            issued_by,
            issued_by_name,
            created_at
        ))

        if action_type in ("Выговор", "Строгий выговор", "Предупреждение"):
            conn.execute("""
            UPDATE employees
            SET warnings_count = warnings_count + 1
            WHERE discord_id = ?
            """, (discord_id,))
        elif action_type in ("Награда", "Благодарность"):
            conn.execute("""
            UPDATE employees
            SET rewards_count = rewards_count + 1
            WHERE discord_id = ?
            """, (discord_id,))

        conn.commit()

    return get_discipline_record(number)


def get_discipline_record(number: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM discipline_records WHERE number = ?",
            (number,)
        ).fetchone()
        return dict(row) if row else None

ACKUP_DIR = BASE_DIR / "backups"


def backup_database() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bot_backup_{timestamp}.db"

    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_path)

    return str(backup_path)


def search_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    return get_employee_by_discord_id(discord_id)


def upsert_employee_from_web(
    discord_id: int,
    fio: str,
    department: str,
    position: str,
    rank_name: str,
    status: str,
    notes: str = ""
) -> dict:
    existing = get_employee_by_discord_id(discord_id)
    joined_at = existing["joined_at"] if existing else now_str()
    probation_until = existing["probation_until"] if existing else None
    cases_count = existing["cases_count"] if existing else 0
    closed_cases_count = existing["closed_cases_count"] if existing else 0
    warnings_count = existing["warnings_count"] if existing else 0
    promotions_count = existing["promotions_count"] if existing else 0
    rewards_count = existing["rewards_count"] if existing else 0

    with get_connection() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO employees (
            discord_id, fio, department, position, rank_name, status,
            joined_at, probation_until, cases_count, closed_cases_count,
            warnings_count, promotions_count, rewards_count, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            discord_id,
            fio,
            department,
            position,
            rank_name,
            status,
            joined_at,
            probation_until,
            cases_count,
            closed_cases_count,
            warnings_count,
            promotions_count,
            rewards_count,
            notes
        ))
        conn.commit()

    return get_employee_by_discord_id(discord_id)

def get_due_probations() -> list[dict]:
    now_dt = datetime.now()
    result = []

    with get_connection() as conn:
        rows = conn.execute("""
        SELECT * FROM employees
        WHERE status = 'Испытательный срок'
        """).fetchall()

    for row in rows:
        if not row["probation_until"]:
            continue

        end_dt = datetime.strptime(row["probation_until"], "%d.%m.%Y %H:%M:%S")
        if end_dt <= now_dt:
            result.append(dict(row))

    return result