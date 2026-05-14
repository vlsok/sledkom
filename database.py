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


def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def get_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError("DATABASE_URL не найден")

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor
    )


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id SERIAL PRIMARY KEY,
                number TEXT UNIQUE,
                user_id BIGINT,
                username TEXT,
                appeal_type TEXT,
                fio TEXT,
                contact TEXT,
                description TEXT,
                status TEXT,
                priority TEXT,
                department TEXT,
                assigned_to BIGINT,
                accepted_by BIGINT,
                accepted_by_name TEXT,
                clarification_requested INTEGER DEFAULT 0,
                clarification_text TEXT,
                citizen_reply_text TEXT,
                citizen_reply_at TEXT,
                resolution_text TEXT,
                archive_flag INTEGER DEFAULT 0,
                log_message_id BIGINT,
                work_channel_id BIGINT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS appeal_history (
                id SERIAL PRIMARY KEY,
                appeal_number TEXT,
                action TEXT,
                actor_id BIGINT,
                actor_name TEXT,
                details TEXT,
                created_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS hr_requests (
                id SERIAL PRIMARY KEY,
                number TEXT UNIQUE,
                user_id BIGINT,
                username TEXT,
                fio TEXT,
                age TEXT,
                experience TEXT,
                reason TEXT,
                status TEXT,
                log_message_id BIGINT,
                processed_by BIGINT,
                processed_by_name TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT UNIQUE,
                fio TEXT,
                department TEXT,
                position TEXT,
                rank_name TEXT,
                status TEXT,
                joined_at TEXT,
                probation_until TEXT,
                cases_count INTEGER DEFAULT 0,
                closed_cases_count INTEGER DEFAULT 0,
                warnings_count INTEGER DEFAULT 0,
                promotions_count INTEGER DEFAULT 0,
                rewards_count INTEGER DEFAULT 0,
                notes TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS discipline_records (
                id SERIAL PRIMARY KEY,
                number TEXT UNIQUE,
                discord_id BIGINT,
                fio TEXT,
                action_type TEXT,
                reason TEXT,
                issued_by BIGINT,
                issued_by_name TEXT,
                created_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_access_requests (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT,
                fio TEXT,
                department TEXT,
                position TEXT,
                reason TEXT,
                status TEXT,
                reviewed_by BIGINT,
                reviewed_by_name TEXT,
                approved_password TEXT,
                created_at TEXT,
                reviewed_at TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT UNIQUE,
                fio TEXT,
                department TEXT,
                password_hash TEXT,
                role TEXT,
                password TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                notes TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_notifications (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT,
                notification_type TEXT,
                title TEXT,
                message TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                sent_at TEXT,
                error_text TEXT
            )
            """)

        conn.commit()


def generate_number(prefix, table):
    year = datetime.now().year

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) as count FROM {table}"
            )

            count = cur.fetchone()["count"] + 1

    return f"{prefix}/{year}/{count:03d}"


def generate_appeal_number():
    return generate_number("СК-ЛО", "appeals")


def generate_hr_number():
    return generate_number("ОК-ЛО", "hr_requests")


def generate_discipline_number():
    return generate_number("ДИС-ЛО", "discipline_records")


def add_appeal_history(
    appeal_number,
    action,
    actor_id=None,
    actor_name=None,
    details=None
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO appeal_history (
                appeal_number,
                action,
                actor_id,
                actor_name,
                details,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                appeal_number,
                action,
                actor_id,
                actor_name,
                details,
                now_str()
            ))

        conn.commit()


def create_appeal(
    user_id,
    username,
    appeal_type,
    fio,
    contact,
    description
):
    number = generate_appeal_number()

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            INSERT INTO appeals (
                number,
                user_id,
                username,
                appeal_type,
                fio,
                contact,
                description,
                status,
                priority,
                department,
                created_at,
                updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                number,
                user_id,
                username,
                appeal_type,
                fio,
                contact,
                description,
                "Принято",
                "Обычный",
                "СО",
                now_str(),
                now_str()
            ))

        conn.commit()

    add_appeal_history(
        number,
        "Создано обращение",
        user_id,
        username
    )

    return get_appeal_by_number(number)


def get_appeal_by_number(number):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM appeals WHERE number = %s",
                (number,)
            )

            row = cur.fetchone()

            return dict(row) if row else None


def get_appeal_history(number, limit=20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM appeal_history
            WHERE appeal_number = %s
            ORDER BY id DESC
            LIMIT %s
            """, (number, limit))

            return [dict(x) for x in cur.fetchall()]


def get_recent_appeals(limit=20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM appeals
            ORDER BY id DESC
            LIMIT %s
            """, (limit,))

            return [dict(x) for x in cur.fetchall()]

def get_active_appeals(limit=50):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM appeals
            WHERE archive_flag = 0
            ORDER BY id DESC
            LIMIT %s
            """, (limit,))

            return [dict(x) for x in cur.fetchall()]
            
def count_appeals_by_status(status):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT COUNT(*) as count
            FROM appeals
            WHERE status = %s
            AND archive_flag = 0
            """, (status,))

            return cur.fetchone()["count"]

def mark_web_notification_sent(
    notification_id,
    error_text=None
):
    with get_connection() as conn:
        with conn.cursor() as cur:

            if error_text:
                cur.execute("""
                UPDATE web_notifications
                SET status = %s,
                    sent_at = %s,
                    error_text = %s
                WHERE id = %s
                """, (
                    "failed",
                    now_str(),
                    error_text[:1000],
                    notification_id
                ))
            else:
                cur.execute("""
                UPDATE web_notifications
                SET status = %s,
                    sent_at = %s
                WHERE id = %s
                """, (
                    "sent",
                    now_str(),
                    notification_id
                ))

        conn.commit()


def get_pending_web_notifications(limit=20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM web_notifications
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT %s
            """, (limit,))

            return [dict(x) for x in cur.fetchall()]


def backup_database():
    BACKUP_DIR.mkdir(exist_ok=True)

    filename = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    data = {}

    tables = [
        "appeals",
        "appeal_history",
        "hr_requests",
        "employees",
        "discipline_records",
        "web_access_requests",
        "web_users",
        "web_notifications"
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:

            for table in tables:
                try:
                    cur.execute(f"SELECT * FROM {table}")
                    data[table] = list(cur.fetchall())
                except:
                    data[table] = []

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            default=str
        )

    return str(filename)
