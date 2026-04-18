import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import random
import string
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")


# =========================
# BASE
# =========================

def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def generate_password(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# =========================
# INIT
# =========================

def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT UNIQUE,
                fio TEXT,
                department TEXT,
                password TEXT,
                role TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                notes TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_access_requests (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT,
                fio TEXT,
                department TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                reviewed_at TEXT,
                reviewed_by BIGINT,
                reviewed_by_name TEXT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS web_notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                text TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                sent_at TEXT,
                error_text TEXT
            )
            """)

        conn.commit()


# =========================
# ACCESS REQUESTS
# =========================

def create_access_request(discord_id, fio, department):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_access_requests (discord_id, fio, department, created_at)
            VALUES (%s, %s, %s, %s)
            """, (discord_id, fio, department, now_str()))
        conn.commit()


def get_recent_access_requests():
    return get_recent_web_access_requests()


def get_recent_web_access_requests():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests ORDER BY id DESC")
            return cur.fetchall()


def get_access_request(request_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests WHERE id = %s", (request_id,))
            return cur.fetchone()


def approve_web_access_request(request_id, reviewed_by, reviewed_by_name):
    access_request = get_access_request(request_id)
    if not access_request:
        return

    password = generate_password()

    create_or_update_web_user(
        discord_id=access_request["discord_id"],
        fio=access_request["fio"],
        department=access_request["department"],
        role="employee",
        password=password
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE web_access_requests
            SET status = 'approved',
                reviewed_at = %s,
                reviewed_by = %s,
                reviewed_by_name = %s
            WHERE id = %s
            """, (now_str(), reviewed_by, reviewed_by_name, request_id))
        conn.commit()

    enqueue_web_notification(
        access_request["discord_id"],
        f"Ваш пароль для входа: {password}"
    )


def reject_web_access_request(request_id, reviewed_by, reviewed_by_name):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            UPDATE web_access_requests
            SET status = 'rejected',
                reviewed_at = %s,
                reviewed_by = %s,
                reviewed_by_name = %s
            WHERE id = %s
            """, (now_str(), reviewed_by, reviewed_by_name, request_id))
        conn.commit()


# =========================
# USERS
# =========================

def create_or_update_web_user(discord_id, fio, department, role, password):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_users (
                discord_id, fio, department, password, role,
                is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET
                fio = EXCLUDED.fio,
                department = EXCLUDED.department,
                password = EXCLUDED.password,
                role = EXCLUDED.role,
                updated_at = %s
            RETURNING *
            """, (
                discord_id,
                fio,
                department,
                password,
                role,
                now_str(),
                now_str(),
                now_str()
            ))
            return cur.fetchone()


def get_user_by_discord(discord_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM web_users WHERE discord_id = %s",
                (discord_id,)
            )
            return cur.fetchone()


# =========================
# NOTIFICATIONS
# =========================

def enqueue_web_notification(user_id, text):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_notifications (user_id, text, created_at)
            VALUES (%s, %s, %s)
            """, (user_id, text, now_str()))
        conn.commit()


def get_pending_notifications():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT * FROM web_notifications
            WHERE status = 'pending'
            ORDER BY id ASC
            """)
            return cur.fetchall()


def mark_web_notification_sent(notification_id: int, error_text: Optional[str] = None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if error_text:
                cur.execute("""
                UPDATE web_notifications
                SET status = 'failed',
                    sent_at = %s,
                    error_text = %s
                WHERE id = %s
                """, (now_str(), error_text[:1000], notification_id))
            else:
                cur.execute("""
                UPDATE web_notifications
                SET status = 'sent',
                    sent_at = %s,
                    error_text = NULL
                WHERE id = %s
                """, (now_str(), notification_id))
        conn.commit()
