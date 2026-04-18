
import json
import os
import secrets
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
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"bot_backup_{timestamp}.json"

    tables = [
        "appeals",
        "appeal_history",
        "hr_requests",
        "employees",
        "discipline_records",
        "web_access_requests",
        "web_users",
        "web_notifications",
    ]

    dump = {"created_at": now_str(), "source": "postgresql", "tables": {}}

    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in tables:
                try:
                    cur.execute(f"SELECT * FROM {table}")
                    dump["tables"][table] = list(cur.fetchall())
                except Exception:
                    dump["tables"][table] = []

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

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_access_requests (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL,
                fio TEXT NOT NULL,
                department TEXT NOT NULL,
                position TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Новая',
                reviewed_by BIGINT,
                reviewed_by_name TEXT,
                approved_password TEXT,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL UNIQUE,
                fio TEXT NOT NULL,
                department TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'employee',
                password TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notes TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_notifications (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL,
                notification_type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error_text TEXT
            )
            """)

            # Migration-safe alters
            cur.execute("ALTER TABLE web_access_requests ADD COLUMN IF NOT EXISTS reviewed_by BIGINT")
            cur.execute("ALTER TABLE web_access_requests ADD COLUMN IF NOT EXISTS reviewed_by_name TEXT")
            cur.execute("ALTER TABLE web_access_requests ADD COLUMN IF NOT EXISTS approved_password TEXT")
            cur.execute("ALTER TABLE web_access_requests ADD COLUMN IF NOT EXISTS reviewed_at TEXT")
            cur.execute("ALTER TABLE web_access_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Новая'")

            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'employee'")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS password TEXT")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS created_at TEXT")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS updated_at TEXT")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS notes TEXT")
            cur.execute("ALTER TABLE web_notifications ADD COLUMN IF NOT EXISTS error_text TEXT")

            now = now_str()
            cur.execute("UPDATE web_users SET role = COALESCE(role, 'employee')")
            cur.execute("UPDATE web_users SET is_active = COALESCE(is_active, 1)")
            cur.execute("UPDATE web_users SET created_at = COALESCE(created_at, %s)", (now,))
            cur.execute("UPDATE web_users SET updated_at = COALESCE(updated_at, created_at, %s)", (now,))
            cur.execute("UPDATE web_users SET password_hash = COALESCE(password_hash, password, 'TEMP_PASSWORD')")
            cur.execute("UPDATE web_access_requests SET status = COALESCE(status, 'Новая')")

        conn.commit()


def generate_number(prefix: str, table: str, year: int | None = None) -> str:
    if year is None:
        year = datetime.now().year
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE number LIKE %s", (f"{prefix}/{year}/%",))
            count = cur.fetchone()["count"] + 1
    return f"{prefix}/{year}/{count:03d}"


def generate_appeal_number() -> str:
    return generate_number("СК-ЛО", "appeals")


def generate_hr_number() -> str:
    return generate_number("ОК-ЛО", "hr_requests")


def generate_discipline_number() -> str:
    return generate_number("ДИС-ЛО", "discipline_records")


def add_appeal_history(appeal_number: str, action: str, actor_id: Optional[int] = None, actor_name: Optional[str] = None, details: Optional[str] = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO appeal_history (appeal_number, action, actor_id, actor_name, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """, (appeal_number, action, actor_id, actor_name, details, now_str()))
        conn.commit()


def determine_department(appeal_type: str, description: str) -> str:
    text = f"{appeal_type} {description}".lower()
    military_words = ["военный", "всо", "воинская часть", "армия", "военнослужащ", "контрактник", "солдат", "офицер"]
    return "ВСО" if any(word in text for word in military_words) else "СО"


def determine_priority(description: str) -> str:
    text = description.lower()
    if any(word in text for word in ["срочно", "угроза", "убийств", "террор", "взрыв"]):
        return "Высокий"
    if any(word in text for word in ["проверка", "жалоба", "заявление"]):
        return "Обычный"
    return "Низкий"


def create_appeal(user_id: int, username: str, appeal_type: str, fio: str, contact: str, description: str) -> dict:
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
                number, user_id, username, appeal_type, fio, contact, description,
                "Принято", priority, department, None, None, None,
                0, None, None, None, None, 0, None, None, created_at, created_at, None
            ))
        conn.commit()
    add_appeal_history(number, "Создано обращение", user_id, username, f"Тип: {appeal_type} / Приоритет: {priority}")
    return get_appeal_by_number(number)


def get_appeal_by_number(number: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE number = %s", (number,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_recent_appeals(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]


def get_appeal_history(number: str, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeal_history WHERE appeal_number = %s ORDER BY id DESC LIMIT %s", (number, limit))
            return [dict(row) for row in cur.fetchall()]


def get_active_appeals(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE archive_flag = 0 ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]


def count_appeals_by_status(status: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM appeals WHERE status = %s AND archive_flag = 0", (status,))
            return cur.fetchone()["count"]


def count_hr_by_status(status: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM hr_requests WHERE status = %s", (status,))
            return cur.fetchone()["count"]


def set_appeal_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET log_message_id = %s, updated_at = %s WHERE number = %s", (message_id, now_str(), number))
        conn.commit()


def set_appeal_work_channel(number: str, channel_id: int, department: str, accepted_by: int, accepted_by_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE appeals
            SET status = %s, work_channel_id = %s, department = %s, accepted_by = %s, accepted_by_name = %s, updated_at = %s
            WHERE number = %s
            """, ("В работе", channel_id, department, accepted_by, accepted_by_name, now_str(), number))
        conn.commit()


def set_appeal_assigned_to(number: str, assigned_to: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET assigned_to = %s, updated_at = %s WHERE number = %s", (assigned_to, now_str(), number))
            cur.execute("UPDATE employees SET cases_count = cases_count + 1 WHERE discord_id = %s", (assigned_to,))
        conn.commit()


def set_appeal_clarification(number: str, text: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET status = %s, clarification_requested = 1, clarification_text = %s, updated_at = %s WHERE number = %s", ("Требует уточнения", text, now_str(), number))
        conn.commit()
    add_appeal_history(number, "Запрошено уточнение", actor_id, actor_name, text)


def set_citizen_reply(number: str, reply_text: str, user_id: int, username: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET citizen_reply_text = %s, citizen_reply_at = %s, updated_at = %s, status = %s WHERE number = %s", (reply_text, now_str(), now_str(), "В работе", number))
        conn.commit()
    add_appeal_history(number, "Поступил ответ на уточнение", user_id, username, reply_text)


def close_appeal(number: str, status: str, resolution_text: str, actor_id: int, actor_name: str) -> None:
    appeal = get_appeal_by_number(number)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET status = %s, resolution_text = %s, updated_at = %s, closed_at = %s WHERE number = %s", (status, resolution_text, now_str(), now_str(), number))
            if appeal and appeal.get("assigned_to"):
                cur.execute("UPDATE employees SET closed_cases_count = closed_cases_count + 1 WHERE discord_id = %s", (appeal["assigned_to"],))
        conn.commit()
    add_appeal_history(number, f"Обращение {status.lower()}", actor_id, actor_name, resolution_text)


def archive_appeal(number: str, actor_id: int, actor_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE appeals SET status = %s, archive_flag = 1, updated_at = %s, closed_at = %s WHERE number = %s", ("Архив", now_str(), now_str(), number))
        conn.commit()
    add_appeal_history(number, "Обращение архивировано", actor_id, actor_name, "Карточка отправлена в архив")


def create_hr_request(user_id: int, username: str, fio: str, age: str, experience: str, reason: str) -> dict:
    number = generate_hr_number()
    created_at = now_str()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO hr_requests (
                number, user_id, username, fio, age, experience, reason, status,
                log_message_id, processed_by, processed_by_name, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (number, user_id, username, fio, age, experience, reason, "На рассмотрении", None, None, None, created_at, created_at))
        conn.commit()
    return get_hr_request_by_number(number)


def get_hr_request_by_number(number: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hr_requests WHERE number = %s", (number,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_recent_hr(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hr_requests ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]


def set_hr_log_message_id(number: str, message_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE hr_requests SET log_message_id = %s, updated_at = %s WHERE number = %s", (message_id, now_str(), number))
        conn.commit()


def update_hr_status(number: str, status: str, processed_by: int, processed_by_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE hr_requests SET status = %s, processed_by = %s, processed_by_name = %s, updated_at = %s WHERE number = %s", (status, processed_by, processed_by_name, now_str(), number))
        conn.commit()


def create_employee(discord_id: int, fio: str, department: str = "СО", position: str = "Стажёр", rank_name: str = "Младший лейтенант юстиции", probation_days: int = 5) -> dict:
    joined_at = now_str()
    probation_until = (datetime.now() + timedelta(days=probation_days)).strftime("%d.%m.%Y %H:%М:%S")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO employees (
                discord_id, fio, department, position, rank_name, status,
                joined_at, probation_until, cases_count, closed_cases_count,
                warnings_count, promotions_count, rewards_count, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET
                fio = EXCLUDED.fio,
                department = EXCLUDED.department,
                position = EXCLUDED.position,
                rank_name = EXCLUDED.rank_name,
                status = EXCLUDED.status,
                joined_at = EXCLUDED.joined_at,
                probation_until = EXCLUDED.probation_until
            """, (discord_id, fio, department, position, rank_name, "Испытательный срок", joined_at, probation_until, 0, 0, 0, 0, 0, None))
        conn.commit()
    return get_employee_by_discord_id(discord_id)


def upsert_employee_from_web(discord_id: int, fio: str, department: str, position: str, rank_name: str, status: str, notes: str = "") -> dict:
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            """, (discord_id, fio, department, position, rank_name, status, joined_at, probation_until, cases_count, closed_cases_count, warnings_count, promotions_count, rewards_count, notes))
        conn.commit()
    return get_employee_by_discord_id(discord_id)


def get_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM employees WHERE discord_id = %s", (discord_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_all_employees() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM employees ORDER BY id DESC")
            return [dict(row) for row in cur.fetchall()]


def search_employee_by_discord_id(discord_id: int) -> Optional[dict]:
    return get_employee_by_discord_id(discord_id)


def update_employee_status(discord_id: int, status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET status = %s WHERE discord_id = %s", (status, discord_id))
        conn.commit()


def update_employee_rank(discord_id: int, rank_name: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET rank_name = %s WHERE discord_id = %s", (rank_name, discord_id))
        conn.commit()


def extend_probation(discord_id: int, days: int) -> dict | None:
    employee = get_employee_by_discord_id(discord_id)
    if not employee:
        return None
    base_dt = datetime.strptime(employee["probation_until"], "%d.%m.%Y %H:%M:%S") if employee.get("probation_until") else datetime.now()
    new_dt = base_dt + timedelta(days=days)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE employees SET probation_until = %s WHERE discord_id = %s", (new_dt.strftime("%d.%m.%Y %H:%M:%S"), discord_id))
        conn.commit()
    return get_employee_by_discord_id(discord_id)


def add_discipline_record(discord_id: int, fio: str, action_type: str, reason: str, issued_by: int, issued_by_name: str) -> dict:
    number = generate_discipline_number()
    created_at = now_str()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO discipline_records (number, discord_id, fio, action_type, reason, issued_by, issued_by_name, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (number, discord_id, fio, action_type, reason, issued_by, issued_by_name, created_at))
            if action_type in ("Выговор", "Строгий выговор", "Предупреждение"):
                cur.execute("UPDATE employees SET warnings_count = warnings_count + 1 WHERE discord_id = %s", (discord_id,))
            elif action_type in ("Награда", "Благодарность"):
                cur.execute("UPDATE employees SET rewards_count = rewards_count + 1 WHERE discord_id = %s", (discord_id,))
        conn.commit()
    return get_discipline_record(number)


def get_discipline_record(number: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM discipline_records WHERE number = %s", (number,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_due_probations() -> list[dict]:
    now_dt = datetime.now()
    result = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM employees WHERE status = 'Испытательный срок'")
            rows = cur.fetchall()
    for row in rows:
        row = dict(row)
        if not row["probation_until"]:
            continue
        end_dt = datetime.strptime(row["probation_until"], "%d.%m.%Y %H:%M:%S")
        if end_dt <= now_dt:
            result.append(row)
    return result


def create_web_access_request(discord_id: int, fio: str, department: str, position: str, reason: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_access_requests (discord_id, fio, department, position, reason, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """, (discord_id, fio, department, position, reason, "Новая", now_str()))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_web_access_request(request_id: int) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_recent_web_access_requests(limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]


def get_latest_web_access_request_by_discord_id(discord_id: int) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests WHERE discord_id = %s ORDER BY id DESC LIMIT 1", (discord_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def count_web_access_requests_by_status(status: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM web_access_requests WHERE status = %s", (status,))
            return cur.fetchone()["count"]


def generate_temp_password(length: int = 10) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_or_update_web_user(discord_id: int, fio: str, department: str, password: str, role: str = "employee") -> dict:
    now = now_str()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_users (
                discord_id, fio, department, password_hash, role, password, is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET
                fio = EXCLUDED.fio,
                department = EXCLUDED.department,
                password_hash = EXCLUDED.password_hash,
                role = EXCLUDED.role,
                password = EXCLUDED.password,
                is_active = EXCLUDED.is_active,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """, (discord_id, fio, department, password, role, password, 1, now, now))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def enqueue_web_notification(discord_id: int, notification_type: str, title: str, message: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_notifications (discord_id, notification_type, title, message, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """, (discord_id, notification_type, title, message, "pending", now_str()))
            row = cur.fetchone()
        conn.commit()
    return dict(row)


def get_pending_web_notifications(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_notifications WHERE status = 'pending' ORDER BY id ASC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]


def mark_web_notification_sent(notification_id: int, error_text: Optional[str] = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if error_text:
                cur.execute("UPDATE web_notifications SET status = %s, sent_at = %s, error_text = %s WHERE id = %s", ("failed", now_str(), error_text[:1000], notification_id))
            else:
                cur.execute("UPDATE web_notifications SET status = %s, sent_at = %s, error_text = NULL WHERE id = %s", ("sent", now_str(), notification_id))
        conn.commit()


def approve_web_access_request(request_id: int, reviewed_by: int = 0, reviewed_by_name: str = "WEB_PANEL") -> dict | None:
    access_request = get_web_access_request(request_id)
    if not access_request:
        return None

    password = generate_temp_password()
    user = create_or_update_web_user(
        discord_id=access_request["discord_id"],
        fio=access_request["fio"],
        department=access_request["department"],
        password=password,
        role="employee",
    )

    enqueue_web_notification(
        discord_id=access_request["discord_id"],
        notification_type="web_access_approved",
        title="Доступ к веб-порталу одобрен",
        message=(
            f"Ваш доступ к веб-порталу одобрен.\n"
            f"Discord ID: {access_request['discord_id']}\n"
            f"Пароль: {password}\n"
            f"Вход: раздел сотрудников на сайте."
        ),
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE web_access_requests
            SET status = %s, reviewed_by = %s, reviewed_by_name = %s, approved_password = %s, reviewed_at = %s
            WHERE id = %s
            RETURNING *
            """, ("Одобрена", reviewed_by, reviewed_by_name, password, now_str(), request_id))
            row = cur.fetchone()
        conn.commit()

    result = dict(row)
    result["web_user"] = user
    return result


def reject_web_access_request(request_id: int, reviewed_by: int = 0, reviewed_by_name: str = "WEB_PANEL") -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE web_access_requests
            SET status = %s, reviewed_by = %s, reviewed_by_name = %s, reviewed_at = %s
            WHERE id = %s
            RETURNING *
            """, ("Отклонена", reviewed_by, reviewed_by_name, now_str(), request_id))
            row = cur.fetchone()
        conn.commit()
    return dict(row) if row else None


def get_web_user_by_discord_id(discord_id: int) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_users WHERE discord_id = %s", (discord_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def authenticate_web_user(discord_id: int, password: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM web_users
            WHERE discord_id = %s
              AND is_active = 1
              AND (password = %s OR password_hash = %s)
            """, (discord_id, password, password))
            row = cur.fetchone()
            return dict(row) if row else None


def get_all_web_users(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_users ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(row) for row in cur.fetchall()]
