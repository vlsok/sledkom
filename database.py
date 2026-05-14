import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import random
import string
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")

# =========================
# БАЗОВЫЕ ФУНКЦИИ
# =========================

def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")

def generate_password(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# =========================
# ИНИЦИАЛИЗАЦИЯ БД
# =========================

def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Пользователи веб-панели
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

            # Заявки на доступ к вебу
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

            # Обращения (Appeals)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                id SERIAL PRIMARY KEY,
                number TEXT UNIQUE,
                discord_id BIGINT,
                fio TEXT,
                text TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT,
                updated_at TEXT,
                notes TEXT
            )
            """)

            # HR Заявки
            cur.execute("""
            CREATE TABLE IF NOT EXISTS hr_requests (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT,
                fio TEXT,
                age TEXT,
                experience TEXT,
                status TEXT DEFAULT 'pending',
                log_message_id BIGINT,
                created_at TEXT
            )
            """)

            # Уведомления
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
            
            # Дисциплинарные записи (заглушка таблицы)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS discipline_records (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                reason TEXT,
                created_at TEXT
            )
            """)

        conn.commit()

# =========================
# ОБРАЩЕНИЯ (APPEALS)
# =========================

def create_appeal(discord_id, fio, text):
    appeal_number = f"AP-{random.randint(10000, 99999)}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO appeals (number, discord_id, fio, text, created_at, status)
                VALUES (%s, %s, %s, %s, %s, 'new')
            """, (appeal_number, discord_id, fio, text, now_str()))
        conn.commit()
    return appeal_number

def get_appeal_by_number(number):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE number = %s", (number,))
            return cur.fetchone()

def get_recent_appeals():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals ORDER BY id DESC LIMIT 50")
            return cur.fetchall()

def count_appeals_by_status(status):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM appeals WHERE status = %s", (status,))
            res = cur.fetchone()
            return res['count'] if res else 0

# =========================
# HR ФУНКЦИИ
# =========================

def create_hr_request(discord_id, fio, age, experience):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO hr_requests (discord_id, fio, age, experience, created_at)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (discord_id, fio, age, experience, now_str()))
            return cur.fetchone()['id']

def count_hr_by_status(status):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hr_requests WHERE status = %s", (status,))
            res = cur.fetchone()
            return res['count'] if res else 0

def get_recent_hr():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hr_requests ORDER BY id DESC LIMIT 20")
            return cur.fetchall()

def set_hr_log_message_id(request_id, message_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE hr_requests SET log_message_id = %s WHERE id = %s", (message_id, request_id))
        conn.commit()

def update_hr_status(request_id, status):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE hr_requests SET status = %s WHERE id = %s", (status, request_id))
        conn.commit()

# =========================
# СОТРУДНИКИ И ДОСТУП
# =========================

def create_employee(discord_id, fio, department, role):
    create_or_update_web_user(discord_id, fio, department, role, generate_password())

def add_discipline_record(user_id, reason):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO discipline_records (user_id, reason, created_at) VALUES (%s, %s, %s)", 
                        (user_id, reason, now_str()))
        conn.commit()

def authenticate_web_user(discord_id, password):
    user = get_user_by_discord(discord_id)
    if user and user['password'] == password and user['is_active']:
        return user
    return None

def create_access_request(discord_id, fio, department):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_access_requests (discord_id, fio, department, created_at)
            VALUES (%s, %s, %s, %s)
            """, (discord_id, fio, department, now_str()))
        conn.commit()

def approve_web_access_request(request_id, reviewed_by, reviewed_by_name):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests WHERE id = %s", (request_id,))
            req = cur.fetchone()
            if not req: return
            pwd = generate_password()
            create_or_update_web_user(req['discord_id'], req['fio'], req['department'], 'employee', pwd)
            cur.execute("""
                UPDATE web_access_requests SET status='approved', reviewed_at=%s, reviewed_by=%s, reviewed_by_name=%s WHERE id=%s
            """, (now_str(), reviewed_by, reviewed_by_name, request_id))
        conn.commit()
        enqueue_web_notification(req['discord_id'], f"Доступ одобрен. Пароль: {pwd}")

def reject_web_access_request(request_id, reviewed_by, reviewed_by_name):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE web_access_requests SET status='rejected', reviewed_at=%s, reviewed_by=%s, reviewed_by_name=%s WHERE id=%s
            """, (now_str(), reviewed_by, reviewed_by_name, request_id))
        conn.commit()

# =========================
# СЛУЖЕБНЫЕ (ВЕБ И УВЕДОМЛЕНИЯ)
# =========================

def get_user_by_discord(discord_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_users WHERE discord_id = %s", (discord_id,))
            return cur.fetchone()

def create_or_update_web_user(discord_id, fio, department, role, password):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO web_users (discord_id, fio, department, password, role, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
            ON CONFLICT (discord_id) DO UPDATE SET 
            fio=EXCLUDED.fio, department=EXCLUDED.department, updated_at=EXCLUDED.updated_at
            """, (discord_id, fio, department, password, role, now_str(), now_str()))
        conn.commit()

def enqueue_web_notification(user_id, text):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_notifications (user_id, text, created_at) VALUES (%s, %s, %s)", (user_id, text, now_str()))
        conn.commit()

def get_pending_notifications():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_notifications WHERE status = 'pending'")
            return cur.fetchall()

def mark_web_notification_sent(notification_id, error_text=None):
    status = 'sent' if not error_text else 'failed'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE web_notifications SET status=%s, sent_at=%s, error_text=%s WHERE id=%s", 
                        (status, now_str(), error_text, notification_id))
        conn.commit()

# =========================
# ЗАГЛУШКИ ДЛЯ ИМПОРТОВ
# =========================

def get_all_employees():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_users WHERE role != 'admin'")
            return cur.fetchall()

def get_all_web_users():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_users")
            return cur.fetchall()

def count_web_access_requests_by_status(status):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM web_access_requests WHERE status = %s", (status,))
            res = cur.fetchone()
            return res['count'] if res else 0

def get_recent_web_access_requests():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests ORDER BY id DESC")
            return cur.fetchall()

def get_due_probations(): return []
def search_employee_by_discord_id(d_id): return get_user_by_discord(d_id)
def upsert_employee_from_web(**kwargs): pass
def backup_database(): pass
def get_access_request(rid):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM web_access_requests WHERE id = %s", (rid,))
            return cur.fetchone()

# Алиасы для совместимости
get_web_access_request = get_access_request
get_web_user_by_discord_id = get_user_by_discord
get_latest_web_access_request_by_discord_id = get_access_request
