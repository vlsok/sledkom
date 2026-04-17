import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / "backups"


def now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL не найден в переменных окружения")

    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)


def backup_database() -> str:
    """
    Для PostgreSQL на Railway нельзя просто копировать .db файл, как в SQLite.
    Поэтому делаем JSON-дамп основных таблиц.
    Важно: на Railway файловая система временная, так что это скорее служебный экспорт.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bot_backup_{timestamp}.json"

    tables = [
        "appeals",
        "appeal_history",
        "hr_requests",
        "employees",
        "discipline_records",
    ]

    dump = {
        "created_at": now_str(),
        "source": "postgresql",
        "tables": {},
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT * FROM {table}")
                rows = cur.fetchall()
                dump["tables"][table] = list(rows)

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2, default=str)

    return str(backup_path)


def init_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                username TEXT NOT NULL,
                appeal_type TEXT NOT NULL,
                fio TEXT NOT NULL,
                contact TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Принято',
                priority TEXT NOT NULL DEFAULT 'Обычный',
                department TEXT,
                assigned_to BIGINT,
                accepted_by BIGINT,
                accepted_by_name TEXT,
                clarification_requested INTEGER NOT NULL DEFAULT 0,
                clarification_text TEXT,
                citizen_reply_text TEXT,
                citizen_reply_at TEXT,
                resolution_text TEXT,
                archive_flag INTEGER NOT NULL DEFAULT 0,
                log_message_id BIGINT,
                work_channel_id BIGINT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS appeal_history (
                id SERIAL PRIMARY KEY,
                appeal_number TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_id BIGINT,
                actor_name TEXT,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS hr_requests (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                username TEXT NOT NULL,
                fio TEXT NOT NULL,
                age TEXT NOT NULL,
                experience TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                log_message_id BIGINT,
                processed_by BIGINT,
                processed_by_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL UNIQUE,
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

            cur.execute("""
            CREATE TABLE IF NOT EXISTS discipline_records (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL UNIQUE,
                discord_id BIGINT NOT NULL,
                fio TEXT NOT NULL,
                action_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                issued_by BIGINT NOT NULL,
                issued_by_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        conn.commit()


def generate_number(prefix: str, table: str, year: int | None = None) -> str:
    if year is None:
        year = datetime.now().year

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE number LIKE %s",
                (f"{prefix}/{year}/%",)
            )
            row = cur.fetchone()
            count = row["count"] + 1

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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO appeal_history (
                appeal_number, action, actor_id, actor_name, details, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO appeals (
                number, user_id, username, appeal_type, fio, contact, description,
                status, priority, department, assigned_to, accepted_by, accepted_by_name,
                clarification_requested, clarification_text, citizen_reply_text, citizen_reply_at,
                resolution_text, archive_flag, log_message_id, work_channel_id, created_at, updated_at, closed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM appeals WHERE number = %s",
                (number,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_recent_appeals(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM appeals ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def get_appeal_history(number: str, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM appeal_history
            WHERE appeal_number = %s
            ORDER BY id DESC
            LIMIT %s
            """, (number, limit))
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def get_active_appeals(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM appeals
            WHERE archive_flag = 0
            ORDER BY id DESC
            LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def count_appeals_by_status(status: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT COUNT(*) AS count
            FROM appeals
            WHERE status = %s AND archive_flag = 0
            """, (status,))
            row = cur.fetchone()
            return row["count"]


def count_hr_by_status(status: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT COUNT(*) AS count
            FROM hr_requests
            WHERE status = %s
            """, (status,))
            row = cur.fetchone()
            return row["count"]


def set_appeal_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET log_message_id = %s, updated_at = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET status = %s, work_channel_id = %s, department = %s, accepted_by = %s, accepted_by_name = %s, updated_at = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET assigned_to = %s, updated_at = %s
            WHERE number = %s
            """, (assigned_to, now_str(), number))

            cur.execute("""
            UPDATE employees
            SET cases_count = cases_count + 1
            WHERE discord_id = %s
            """, (assigned_to,))
        conn.commit()


def set_appeal_clarification(number: str, text: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET status = %s, clarification_requested = 1, clarification_text = %s, updated_at = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET citizen_reply_text = %s, citizen_reply_at = %s, updated_at = %s, status = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET status = %s, resolution_text = %s, updated_at = %s, closed_at = %s
            WHERE number = %s
            """, (
                status,
                resolution_text,
                now_str(),
                now_str(),
                number
            ))

            if appeal and appeal.get("assigned_to"):
                cur.execute("""
                UPDATE employees
                SET closed_cases_count = closed_cases_count + 1
                WHERE discord_id = %s
                """, (appeal["assigned_to"],))
        conn.commit()

    add_appeal_history(number, f"Обращение {status.lower()}", actor_id, actor_name, resolution_text)


def archive_appeal(number: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET status = %s, archive_flag = 1, updated_at = %s, closed_at = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO hr_requests (
                number, user_id, username, fio, age, experience, reason,
                status, log_message_id, processed_by, processed_by_name, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM hr_requests WHERE number = %s",
                (number,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_recent_hr(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM hr_requests ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def set_hr_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE hr_requests
            SET log_message_id = %s, updated_at = %s
            WHERE number = %s
            """, (message_id, now_str(), number))
        conn.commit()


def update_hr_status(number: str, status: str, processed_by: int, processed_by_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE hr_requests
            SET status = %s, processed_by = %s, processed_by_name = %s, updated_at = %s
            WHERE number = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO employees (
                discord_id, fio, department, position, rank_name, status,
                joined_at, probation_until, cases_count, closed_cases_count,
                warnings_count, promotions_count, rewards_count, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET
                fio = EXCLUDED.fio,
                department = EXCLUDED.department,
                position = EXCLUDED.position,
                rank_name = EXCLUDED.rank_name,
                status = EXCLUDED.status,
                joined_at = EXCLUDED.joined_at,
                probation_until = EXCLUDED.probation_until
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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO employees (
                discord_id, fio, department, position, rank_name, status,
                joined_at, probation_until, cases_count, closed_cases_count,
                warnings_count, promotions_count, rewards_count, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET
                fio = EXCLUDED.fio,
                department = EXCLUDED.department,
                position = EXCLUDED.position,
                rank_name = EXCLUDED.rank_name,
                status = EXCLUDED.status,
                joined_at = EXCLUDED.joined_at,
                probation_until = EXCLUDED.probation_until,
                cases_count = EXCLUDED.cases_count,
                closed_cases_count = EXCLUDED.closed_cases_count,
                warnings_count = EXCLUDED.warnings_count,
                promotions_count = EXCLUDED.promotions_count,
                rewards_count = EXCLUDED.rewards_count,
                notes = EXCLUDED.notes
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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM employees WHERE discord_id = %s",
                (discord_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_all_employees() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM employees ORDER BY id DESC")
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def search_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    return get_employee_by_discord_id(discord_id)


def update_employee_status(discord_id: int, status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE employees
            SET status = %s
            WHERE discord_id = %s
            """, (status, discord_id))
        conn.commit()


def update_employee_rank(discord_id: int, rank_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE employees
            SET rank_name = %s
            WHERE discord_id = %s
            """, (rank_name, discord_id))
        conn.commit()


def extend_probation(discord_id: int, days: int) -> dict | None:
    employee = get_employee_by_discord_id(discord_id)
    if not employee:
        return None

    base_dt = datetime.strptime(employee["probation_until"], "%d.%m.%Y %H:%M:%S") if employee.get("probation_until") else datetime.now()
    new_dt = base_dt + timedelta(days=days)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE employees
            SET probation_until = %s
            WHERE discord_id = %s
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
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO discipline_records (
                number, discord_id, fio, action_type, reason, issued_by, issued_by_name, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                cur.execute("""
                UPDATE employees
                SET warnings_count = warnings_count + 1
                WHERE discord_id = %s
                """, (discord_id,))
            elif action_type in ("Награда", "Благодарность"):
                cur.execute("""
                UPDATE employees
                SET rewards_count = rewards_count + 1
                WHERE discord_id = %s
                """, (discord_id,))
        conn.commit()

    return get_discipline_record(number)


def get_discipline_record(number: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM discipline_records WHERE number = %s",
                (number,)
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_due_probations() -> list[dict]:
    now_dt = datetime.now()
    result = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM employees
            WHERE status = 'Испытательный срок'
            """)
            rows = cur.fetchall()

    for row in rows:
        row_dict = dict(row)
        if not row_dict["probation_until"]:
            continue

        end_dt = datetime.strptime(row_dict["probation_until"], "%d.%m.%Y %H:%M:%S")
        if end_dt <= now_dt:
            result.append(row_dict)

    return result
