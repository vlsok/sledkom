
import os
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    send_from_directory,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from database import (
    init_db,
    count_appeals_by_status,
    count_hr_by_status,
    get_due_probations,
    get_recent_appeals,
    get_all_employees,
    search_employee_by_discord_id,
    upsert_employee_from_web,
    backup_database,
    get_appeal_by_number,
    get_connection,
    get_recent_web_access_requests,
    get_web_access_request,
    count_web_access_requests_by_status,
    approve_web_access_request,
    reject_web_access_request,
    get_latest_web_access_request_by_discord_id,
    authenticate_web_user,
    get_all_web_users,
    get_web_user_by_discord_id,
)

app = Flask(__name__)
app.secret_key = os.getenv("WEB_PANEL_SECRET", "sk_panel_secret_key_change_me")
WEB_PANEL_PASSWORD = os.getenv("WEB_PANEL_PASSWORD", "12345")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"doc", "docx", "pdf", "png"}
MAX_UPLOAD_MB = 10

init_db()


# =========================
# EXTRA TABLES
# =========================

def init_extra_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS employee_documents (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                file_ext TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS leadership_messages (
                id SERIAL PRIMARY KEY,
                discord_id BIGINT NOT NULL,
                fio TEXT,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Новая',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                attachment_filename TEXT,
                attachment_stored_filename TEXT
            )
            """)
        conn.commit()


init_extra_tables()


# =========================
# HELPERS
# =========================

def now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file_storage, prefix: str) -> tuple[str, str]:
    original_name = file_storage.filename or "file"
    ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else ""
    stored = f"{prefix}_{uuid.uuid4().hex}.{ext}" if ext else f"{prefix}_{uuid.uuid4().hex}"
    file_storage.save(UPLOAD_DIR / stored)
    return original_name, stored


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("panel_auth"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def staff_login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("staff_auth"):
            return redirect(url_for("staff_login"))
        return func(*args, **kwargs)
    return wrapper


def get_stats():
    return {
        "new_count": count_appeals_by_status("Принято"),
        "work_count": count_appeals_by_status("В работе"),
        "clarify_count": count_appeals_by_status("Требует уточнения"),
        "closed_count": count_appeals_by_status("Закрыто"),
        "rejected_count": count_appeals_by_status("Отказано"),
        "hr_count": count_hr_by_status("На рассмотрении"),
        "probation_count": len(get_due_probations()),
        "access_new_count": count_web_access_requests_by_status("Новая"),
        "access_approved_count": count_web_access_requests_by_status("Одобрена"),
    }


def get_department_stats(employees):
    return {
        "so_count": len([x for x in employees if x.get("department") == "СО"]),
        "vso_count": len([x for x in employees if x.get("department") == "ВСО"]),
    }


def get_top_employees(employees, limit=5):
    return sorted(
        employees,
        key=lambda x: (x.get("closed_cases_count", 0), x.get("cases_count", 0)),
        reverse=True,
    )[:limit]


def filter_employees(employees, department="", fio="", status=""):
    result = employees
    if department:
        result = [x for x in result if (x.get("department") or "") == department]
    if fio:
        result = [x for x in result if fio.lower() in (x.get("fio") or "").lower()]
    if status:
        result = [x for x in result if status.lower() in (x.get("status") or "").lower()]
    return result


def filter_appeals(appeals, appeal_status="", appeal_department="", appeal_number="", appeal_priority=""):
    result = appeals
    if appeal_status:
        result = [x for x in result if (x.get("status") or "") == appeal_status]
    if appeal_department:
        result = [x for x in result if (x.get("department") or "") == appeal_department]
    if appeal_number:
        result = [x for x in result if appeal_number.lower() in (x.get("number") or "").lower()]
    if appeal_priority:
        result = [x for x in result if (x.get("priority") or "") == appeal_priority]
    return result


def load_discipline_records(limit: int = 200):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM discipline_records ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(x) for x in cur.fetchall()]


def filter_discipline(records, fio="", action_type=""):
    result = records
    if fio:
        result = [x for x in result if fio.lower() in (x.get("fio") or "").lower()]
    if action_type:
        result = [x for x in result if action_type.lower() in (x.get("action_type") or "").lower()]
    return result


def get_appeal_history_for_page(number: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM appeal_history
                WHERE appeal_number = %s
                ORDER BY id DESC
                LIMIT 30
            """, (number,))
            return [dict(x) for x in cur.fetchall()]


def update_appeal_from_web(number: str, form: dict):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE appeals
                SET status = %s,
                    department = %s,
                    priority = %s,
                    assigned_to = %s,
                    clarification_text = %s,
                    resolution_text = %s,
                    updated_at = %s
                WHERE number = %s
            """, (
                form.get("status", "").strip(),
                form.get("department", "").strip(),
                form.get("priority", "").strip(),
                int(form["assigned_to"]) if form.get("assigned_to", "").strip().isdigit() else None,
                form.get("clarification_text", "").strip() or None,
                form.get("resolution_text", "").strip() or None,
                now_str(),
                number,
            ))
        conn.commit()


def update_employee_from_web(discord_id: int, form: dict):
    upsert_employee_from_web(
        discord_id=discord_id,
        fio=form.get("fio", "").strip(),
        department=form.get("department", "").strip(),
        position=form.get("position", "").strip(),
        rank_name=form.get("rank_name", "").strip(),
        status=form.get("status", "").strip(),
        notes=form.get("notes", "").strip(),
    )


def save_status_chart():
    stats = get_stats()
    labels = ["Новые", "В работе", "Уточнение", "Закрытые", "Отказы"]
    values = [stats["new_count"], stats["work_count"], stats["clarify_count"], stats["closed_count"], stats["rejected_count"]]
    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.title("Статусы обращений")
    plt.tight_layout()
    path = STATIC_DIR / "appeals_status_chart.png"
    plt.savefig(path, dpi=140)
    plt.close()
    return "appeals_status_chart.png"


def save_employee_chart(employees):
    top = get_top_employees(employees, 7)
    labels = [x.get("fio", "—")[:18] for x in top] or ["Нет данных"]
    values = [x.get("closed_cases_count", 0) for x in top] or [0]
    plt.figure(figsize=(9, 4.8))
    plt.bar(labels, values)
    plt.title("Топ сотрудников по закрытым делам")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    path = STATIC_DIR / "employees_top_chart.png"
    plt.savefig(path, dpi=140)
    plt.close()
    return "employees_top_chart.png"


def save_department_chart(employees):
    dep_stats = get_department_stats(employees)
    labels = ["СО", "ВСО"]
    values = [dep_stats["so_count"], dep_stats["vso_count"]]
    plt.figure(figsize=(6, 4.2))
    plt.bar(labels, values)
    plt.title("Сотрудники по подразделениям")
    plt.tight_layout()
    path = STATIC_DIR / "departments_chart.png"
    plt.savefig(path, dpi=140)
    plt.close()
    return "departments_chart.png"


# =========================
# STAFF DATA ACCESS
# =========================

def staff_get_documents(discord_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM employee_documents
                WHERE discord_id = %s
                ORDER BY id DESC
            """, (discord_id,))
            return [dict(row) for row in cur.fetchall()]


def staff_add_document(discord_id: int, original_filename: str, stored_filename: str, file_ext: str, description: str = ""):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO employee_documents (
                    discord_id, original_filename, stored_filename, file_ext, description, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (discord_id, original_filename, stored_filename, file_ext, description, now_str()))
        conn.commit()


def staff_get_messages(discord_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM leadership_messages
                WHERE discord_id = %s
                ORDER BY id DESC
            """, (discord_id,))
            return [dict(row) for row in cur.fetchall()]


def staff_add_leadership_message(discord_id: int, fio: str, subject: str, message_text: str, attachment_filename=None, attachment_stored_filename=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO leadership_messages (
                    discord_id, fio, subject, message, status, created_at, attachment_filename, attachment_stored_filename
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (discord_id, fio, subject, message_text, "Новая", now_str(), attachment_filename, attachment_stored_filename))
        conn.commit()


def leadership_get_all_messages():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM leadership_messages
                ORDER BY id DESC
                LIMIT 300
            """)
            return [dict(row) for row in cur.fetchall()]


def staff_update_password(discord_id: int, new_password: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE web_users
                SET password = %s,
                    password_hash = %s,
                    updated_at = %s
                WHERE discord_id = %s
            """, (new_password, new_password, now_str(), discord_id))
        conn.commit()


# =========================
# RENDERERS
# =========================

def render_page(title: str, content: str, active: str = "dashboard"):
    message = request.args.get("message", "")
    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>{{ title }}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root { --bg1:#fff8f8; --bg2:#fff3f3; --bg3:#ffe8e8; --text:#3a1010; --muted:#8a5d5d; --line:#e7c4c4; --blue:#a50000; --blue2:#7d0000; --radius:20px; }
            * { box-sizing:border-box; }
            body { margin:0; font-family:Arial,sans-serif; color:var(--text);
                background: radial-gradient(circle at top right, rgba(37,99,235,.12), transparent 20%),
                            radial-gradient(circle at top left, rgba(124,58,237,.10), transparent 18%),
                            linear-gradient(135deg, var(--bg1), var(--bg2), var(--bg3)); min-height:100vh; }
            .layout { display:grid; grid-template-columns:280px 1fr; min-height:100vh; }
            .sidebar { background:linear-gradient(180deg,#8b0000,#b30000); color:#fff; border-right:1px solid rgba(255,255,255,.18); padding:24px 18px; }
            .brand h1 { margin:0 0 8px 0; font-size:22px; }
            .brand p { margin:0 0 24px 0; color:var(--muted); font-size:14px; }
            .nav { display:grid; gap:10px; }
            .nav a { display:block; padding:14px; border-radius:14px; color:#fff5f5; text-decoration:none; border:1px solid transparent; }
            .nav a:hover { background:rgba(255,255,255,.14); border-color:rgba(255,255,255,.22); }
            .nav a.active { background:linear-gradient(135deg, rgba(255,255,255,.20), rgba(255,220,220,.14)); border-color:rgba(255,255,255,.28); }
            .main { padding:28px; }
            .topbar { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:20px; flex-wrap:wrap; }
            .topbar h2 { margin:0; font-size:26px; }
            .btn { display:inline-block; padding:11px 16px; border:none; border-radius:12px; background:var(--blue); color:white; font-weight:bold; cursor:pointer; text-decoration:none; }
            .btn.secondary { background:#ffffff; color:#a50000; border:1px solid #d8aaaa; }
            .btn.red { background:#a50000; }
            .message { padding:14px 16px; border-radius:14px; background:rgba(165,0,0,.08); border:1px solid rgba(165,0,0,.18); margin-bottom:20px; }
            .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:24px; }
            .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:24px; }
            .row-3 { display:grid; grid-template-columns:1.2fr .8fr .8fr; gap:18px; margin-bottom:24px; }
            .card { background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:var(--radius); padding:18px; margin-bottom:20px; }
            .stat-number { font-size:32px; font-weight:bold; margin-top:8px; }
            table { width:100%; border-collapse:collapse; }
            th, td { padding:12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
            th { background:#9d1111; color:#fff; }
            input, select, textarea { width:100%; padding:11px 12px; border-radius:12px; border:1px solid #d7b1b1; background:#fff; color:#3a1010; margin-bottom:12px; outline:none; }
            textarea { min-height:100px; resize:vertical; }
            .toolbar form { display:flex; gap:10px; flex-wrap:wrap; width:100%; }
            .toolbar input, .toolbar select { margin-bottom:0; min-width:170px; flex:1; }
            .mini-item { padding:12px; border-radius:14px; background:#fff8f8; border:1px solid #edd1d1; margin-bottom:10px; }
            .big-center { font-size:18px; font-weight:bold; margin-bottom:6px; }
            .small { font-size:13px; color:var(--muted); }
            .box { background:#fffafa; border:1px solid #efd0d0; border-radius:14px; padding:14px; }
            .kv { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }
            .timeline-item { padding:12px; border-radius:14px; background:#fff8f8; border:1px solid #edd1d1; margin-bottom:10px; }
            @media (max-width:1100px){ .layout{grid-template-columns:1fr;} .row-2,.row-3,.kv{grid-template-columns:1fr;} }
        </style>
    </head>
    <body>
        <div class="layout">
            <aside class="sidebar">
                <div class="brand">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                        <div style="width:54px;height:54px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;color:#8b0000;font-weight:900;font-size:20px;border:3px solid rgba(255,255,255,.55);box-shadow:0 6px 18px rgba(0,0,0,.18);">СК</div>
                        <div>
                            <h1 style="margin:0;font-size:22px;color:#fff;">СУ СК</h1>
                            <p style="margin:4px 0 0 0;color:#ffe7e7;font-size:13px;">Следственный портал</p>
                        </div>
                    </div>
                    <div style="padding:12px 14px;border-radius:14px;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.16);font-size:13px;line-height:1.5;color:#fff5f5;">
                        Личный кабинет руководства в красно-белой теме.
                    </div>
                </div>
                <nav class="nav">
                    <a href="/admin" class="{{ 'active' if active == 'dashboard' else '' }}">📊 Дашборд</a>
                    <a href="/access-requests" class="{{ 'active' if active == 'access_requests' else '' }}">🛂 Заявки на доступ</a>
                    <a href="/web-users" class="{{ 'active' if active == 'web_users' else '' }}">👥 Веб-сотрудники</a>
                    <a href="/leadership-inbox" class="{{ 'active' if active == 'leadership' else '' }}">📨 Руководству</a>
                    <a href="/appeals" class="{{ 'active' if active == 'appeals' else '' }}">📨 Обращения</a>
                    <a href="/employees" class="{{ 'active' if active == 'employees' else '' }}">👥 Кадры</a>
                    <a href="/analytics" class="{{ 'active' if active == 'analytics' else '' }}">📈 Аналитика</a>
                    <a href="/discipline" class="{{ 'active' if active == 'discipline' else '' }}">⚖️ Дисциплина</a>
                    <a href="/">🏠 На главную</a>
                    <a href="/logout">🚪 Выход</a>
                </nav>
            </aside>
            <main class="main">
                <div class="topbar">
                    <h2>{{ title }}</h2>
                    <div>
                        <form method="post" action="/backup" style="display:inline;">
                            <button class="btn" type="submit">💾 Бэкап базы</button>
                        </form>
                    </div>
                </div>
                {% if message %}<div class="message">{{ message }}</div>{% endif %}
                {{ content|safe }}
            </main>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, title=title, content=content, active=active, message=message)


def render_staff_page(title: str, content: str, active: str = "dashboard"):
    message = request.args.get("message", "")
    user = session.get("staff_user", {})
    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>{{ title }}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root { --bg1:#08111f; --bg2:#0f172a; --bg3:#111827; --text:#e5e7eb; --muted:#94a3b8; --line:#334155; --blue:#2563eb; --radius:20px; }
            * { box-sizing:border-box; }
            body { margin:0; font-family:Arial,sans-serif; color:var(--text); background:linear-gradient(135deg,var(--bg1),var(--bg2),var(--bg3)); min-height:100vh; }
            .layout { display:grid; grid-template-columns:280px 1fr; min-height:100vh; }
            .sidebar { background:rgba(10,16,30,.88); padding:24px 18px; border-right:1px solid rgba(148,163,184,.08); }
            .brand h1 { margin:0 0 8px 0; font-size:22px; }
            .brand p { margin:0 0 24px 0; color:var(--muted); font-size:14px; }
            .nav { display:grid; gap:10px; }
            .nav a { display:block; padding:14px; border-radius:14px; color:#fff5f5; text-decoration:none; border:1px solid transparent; }
            .nav a:hover { background:rgba(37,99,235,.12); }
            .nav a.active { background:linear-gradient(135deg, rgba(37,99,235,.22), rgba(124,58,237,.16)); }
            .main { padding:28px; }
            .topbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap; gap:16px; }
            .topbar h2 { margin:0; font-size:26px; }
            .btn { display:inline-block; padding:11px 16px; border:none; border-radius:12px; background:var(--blue); color:white; font-weight:bold; cursor:pointer; text-decoration:none; }
            .btn.secondary { background:#ffffff; color:#a50000; border:1px solid #d8aaaa; }
            .message { padding:14px 16px; border-radius:14px; background:rgba(165,0,0,.08); border:1px solid rgba(165,0,0,.18); margin-bottom:20px; }
            .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:24px; }
            .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:24px; }
            .card { background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:20px; padding:18px; margin-bottom:20px; }
            .stat-number { font-size:28px; font-weight:bold; margin-top:8px; }
            .box { background:#fffafa; border:1px solid #efd0d0; border-radius:14px; padding:14px; }
            .kv { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }
            table { width:100%; border-collapse:collapse; }
            th, td { padding:12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
            th { background:#9d1111; color:#fff; }
            input, select, textarea { width:100%; padding:11px 12px; border-radius:12px; border:1px solid #d7b1b1; background:#fff; color:#3a1010; margin-bottom:12px; outline:none; }
            textarea { min-height:120px; resize:vertical; }
            @media (max-width:1100px){ .layout{grid-template-columns:1fr;} .row-2,.kv{grid-template-columns:1fr;} }
        </style>
    </head>
    <body>
        <div class="layout">
            <aside class="sidebar">
                <div class="brand">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                        <div style="width:54px;height:54px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;color:#8b0000;font-weight:900;font-size:20px;border:3px solid rgba(255,255,255,.55);box-shadow:0 6px 18px rgba(0,0,0,.18);">СК</div>
                        <div>
                            <h1 style="margin:0;font-size:21px;color:#fff;">Кабинет сотрудника</h1>
                            <p style="margin:4px 0 0 0;color:#ffe7e7;font-size:13px;">{{ user.get('fio', 'Сотрудник') }} · {{ user.get('department', '—') }}</p>
                        </div>
                    </div>
                </div>
                <nav class="nav">
                    <a href="/staff/dashboard" class="{{ 'active' if active == 'dashboard' else '' }}">📊 Главная</a>
                    <a href="/staff/documents" class="{{ 'active' if active == 'documents' else '' }}">📂 Мои документы</a>
                    <a href="/staff/upload" class="{{ 'active' if active == 'upload' else '' }}">⬆️ Загрузить документ</a>
                    <a href="/staff/leadership" class="{{ 'active' if active == 'leadership' else '' }}">📨 Руководству</a>
                    <a href="/staff/change-password" class="{{ 'active' if active == 'password' else '' }}">🔐 Сменить пароль</a>
                    <a href="/">🏠 На главную</a>
                    <a href="/staff/logout">🚪 Выход</a>
                </nav>
            </aside>
            <main class="main">
                <div class="topbar">
                    <h2>{{ title }}</h2>
                    <a class="btn secondary" href="/staff/dashboard">↻ Обновить</a>
                </div>
                {% if message %}<div class="message">{{ message }}</div>{% endif %}
                {{ content|safe }}
            </main>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, title=title, content=content, active=active, message=message, user=user)


# =========================
# PUBLIC + LOGIN
# =========================

@app.route("/")
def public_index():
    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>СУ СК — Портал</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root { --bg1:#08111f; --bg2:#0f172a; --bg3:#111827; --text:#e5e7eb; --muted:#94a3b8; --blue:#2563eb; --blue2:#1d4ed8; --radius:24px; }
            body { margin:0; font-family:Arial,sans-serif; color:var(--text); background:
                radial-gradient(circle at top right, rgba(37,99,235,.16), transparent 20%),
                radial-gradient(circle at top left, rgba(124,58,237,.12), transparent 18%),
                linear-gradient(135deg, var(--bg1), var(--bg2), var(--bg3)); min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
            .shell { width:100%; max-width:1100px; }
            .hero { text-align:center; margin-bottom:26px; }
            .hero h1 { font-size:40px; margin:0 0 12px 0; }
            .hero p { margin:0 auto; max-width:720px; color:var(--muted); line-height:1.6; font-size:16px; }
            .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:20px; }
            .card { background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:var(--radius); padding:24px; }
            .card h3 { margin:0 0 12px 0; font-size:22px; }
            .card p { margin:0 0 20px 0; color:var(--muted); line-height:1.6; min-height:90px;color:#7a4b4b; }
            .btn { display:inline-block; padding:12px 18px; border-radius:14px; background:#a50000; color:white; text-decoration:none; font-weight:bold; border:none; }
            .btn:hover { background:var(--blue2); }
        </style>
    </head>
    <body>
        <div class="shell">
            <div class="hero" style="margin-bottom:30px;">
                <div style="display:flex;justify-content:center;margin-bottom:18px;">
                    <div style="width:88px;height:88px;border-radius:50%;background:#9d1111;color:#fff;display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:900;box-shadow:0 14px 34px rgba(139,0,0,.18);border:6px solid #fff;">СК</div>
                </div>
                <h1 style="color:#8b0000;">СУ СК — Веб-портал</h1>
                <p>Тестовая красно-белая тема в официальном стиле. Раздел сотрудника включает кабинет, документы и сообщения руководству.</p>
            </div>
            <div class="grid">
                <div class="card">
                    <h3>🔐 Мой раздел</h3>
                    <p>Закрытая административная панель руководства.</p>
                    <a class="btn" href="/login">Открыть раздел</a>
                </div>
                <div class="card">
                    <h3>👥 Раздел сотрудников</h3>
                    <p>Личный кабинет сотрудника: вход, документы, пароль, сообщения руководству.</p>
                    <a class="btn" href="/staff-login">Перейти</a>
                </div>
                <div class="card">
                    <h3>🛂 Запрос доступа</h3>
                    <p>Подача заявки на доступ к кабинету сотрудника.</p>
                    <a class="btn" href="/request-access">Открыть форму</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(template)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password == WEB_PANEL_PASSWORD:
            session["panel_auth"] = True
            return redirect("/admin")
        error = "Неверный пароль."

    template = """
    <!doctype html>
    <html lang="ru"><head><meta charset="utf-8"><title>Вход в панель</title><meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { margin:0; font-family:Arial,sans-serif; background:linear-gradient(180deg,#fff7f7,#fff0f0,#ffe8e8); color:#3a1010; min-height:100vh; }
        .login-wrap { display:flex; min-height:100vh; align-items:center; justify-content:center; padding:24px; }
        .login-card { width:100%; max-width:420px; background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:24px; padding:26px; }
        h1 { margin:0 0 10px 0; } p { color:#8a5d5d; margin-bottom:18px; }
        input { width:100%; padding:12px; border-radius:12px; border:1px solid #d7b1b1; background:#fff; color:#3a1010; margin-bottom:14px; box-sizing:border-box; }
        button { width:100%; padding:12px; border:none; border-radius:12px; background:#a50000; color:white; font-weight:bold; cursor:pointer; }
        .error { margin-top:12px; padding:12px; border-radius:12px; background:rgba(220,38,38,.16); color:#fecaca; }
        .back { display:inline-block; margin-top:16px; color:#8a5d5d; text-decoration:none; }
    </style></head>
    <body><div class="login-wrap"><div class="login-card">
        <h1>🔐 Вход в веб-панель</h1><p>Панель управления СУ СК</p>
        <form method="post">
            <input type="password" name="password" placeholder="Введите пароль" required>
            <button type="submit">Войти</button>
        </form>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <a class="back" href="/">← Вернуться на главную</a>
    </div></div></body></html>
    """
    return render_template_string(template, error=error)


@app.route("/logout")
def logout():
    session.pop("panel_auth", None)
    return redirect("/login")


@app.route("/request-access", methods=["GET", "POST"])
def request_access():
    error = ""
    success = ""
    if request.method == "POST":
        discord_id_text = request.form.get("discord_id", "").strip()
        fio = request.form.get("fio", "").strip()
        department = request.form.get("department", "").strip()
        position = request.form.get("position", "").strip()
        reason = request.form.get("reason", "").strip()

        if not discord_id_text.isdigit():
            error = "Discord ID должен быть числом."
        else:
            discord_id = int(discord_id_text)
            approved_user = get_web_user_by_discord_id(discord_id)
            latest_request = get_latest_web_access_request_by_discord_id(discord_id)

            if approved_user:
                success = "Доступ уже одобрен. Используйте вход для сотрудников."
            elif latest_request and latest_request.get("status") == "Новая":
                success = "Заявка уже отправлена и ожидает рассмотрения."
            else:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO web_access_requests (
                                discord_id, fio, department, position, reason, status, created_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (discord_id, fio, department, position, reason, "Новая", now_str()))
                    conn.commit()
                success = "Заявка на доступ отправлена."

    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>Запрос доступа</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { margin:0; font-family:Arial,sans-serif; background:linear-gradient(180deg,#fff7f7,#fff0f0,#ffe8e8); color:#3a1010; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
            .card { width:100%; max-width:680px; background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:24px; padding:26px; }
            h1 { margin:0 0 12px 0; } p { color:#8a5d5d; line-height:1.6; }
            input, select, textarea { width:100%; padding:12px; border-radius:12px; border:1px solid #d7b1b1; background:#fff; color:#3a1010; margin-bottom:12px; box-sizing:border-box; }
            textarea { min-height:110px; resize:vertical; }
            button, a.btn { display:inline-block; padding:12px 16px; border:none; border-radius:12px; background:#a50000; color:white; text-decoration:none; font-weight:bold; cursor:pointer; }
            a.secondary { background:#ffffff; color:#a50000; border:1px solid #d8aaaa; }
            .error { margin-bottom:12px; padding:12px; border-radius:12px; background:rgba(220,38,38,.16); color:#fecaca; }
            .success { margin-bottom:12px; padding:12px; border-radius:12px; background:rgba(22,163,74,.16); color:#bbf7d0; }
            .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:8px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🛂 Запрос доступа сотрудника</h1>
            <p>Заполните форму для получения доступа к разделу сотрудников.</p>
            {% if error %}<div class="error">{{ error }}</div>{% endif %}
            {% if success %}<div class="success">{{ success }}</div>{% endif %}
            <form method="post">
                <input type="text" name="discord_id" placeholder="Discord ID" required>
                <input type="text" name="fio" placeholder="ФИО" required>
                <select name="department" required>
                    <option value="СО">СО</option>
                    <option value="ВСО">ВСО</option>
                </select>
                <input type="text" name="position" placeholder="Должность" required>
                <textarea name="reason" placeholder="Причина запроса доступа" required></textarea>
                <div class="actions">
                    <button type="submit">Отправить заявку</button>
                    <a class="btn secondary" href="/staff-login">Вход сотрудников</a>
                    <a class="btn secondary" href="/">На главную</a>
                </div>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, error=error, success=success)


@app.route("/staff-login", methods=["GET", "POST"])
def staff_login():
    error = ""
    if request.method == "POST":
        discord_id_text = request.form.get("discord_id", "").strip()
        password = request.form.get("password", "").strip()
        if not discord_id_text.isdigit():
            error = "Discord ID должен быть числом."
        else:
            user = authenticate_web_user(int(discord_id_text), password)
            if user:
                session["staff_auth"] = True
                session["staff_user"] = user
                return redirect("/staff/dashboard")
            error = "Неверный Discord ID или пароль."

    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>Вход сотрудников</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { margin:0; font-family:Arial,sans-serif; background:linear-gradient(180deg,#fff7f7,#fff0f0,#ffe8e8); color:#3a1010; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
            .card { width:100%; max-width:560px; background:#ffffff; border:1px solid #f0d0d0; box-shadow:0 14px 34px rgba(139,0,0,.08); border-radius:24px; padding:26px; }
            h1 { margin:0 0 12px 0; } p { color:#8a5d5d; line-height:1.6; }
            input { width:100%; padding:12px; border-radius:12px; border:1px solid #d7b1b1; background:#fff; color:#3a1010; margin-bottom:12px; box-sizing:border-box; }
            button, a.btn { display:inline-block; padding:12px 16px; border:none; border-radius:12px; background:#a50000; color:white; text-decoration:none; font-weight:bold; cursor:pointer; }
            a.secondary { background:#ffffff; color:#a50000; border:1px solid #d8aaaa; }
            .error { margin-bottom:12px; padding:12px; border-radius:12px; background:rgba(220,38,38,.16); color:#fecaca; }
            .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:8px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>👥 Вход сотрудников</h1>
            <p>Используйте Discord ID и пароль, который пришёл после одобрения заявки.</p>
            {% if error %}<div class="error">{{ error }}</div>{% endif %}
            <form method="post">
                <input type="text" name="discord_id" placeholder="Discord ID" required>
                <input type="password" name="password" placeholder="Пароль" required>
                <div class="actions">
                    <button type="submit">Войти</button>
                    <a class="btn secondary" href="/request-access">Запросить доступ</a>
                    <a class="btn secondary" href="/">На главную</a>
                </div>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, error=error)


@app.route("/staff/logout")
def staff_logout():
    session.pop("staff_auth", None)
    session.pop("staff_user", None)
    return redirect("/staff-login")


# =========================
# ADMIN ROUTES
# =========================

@app.route("/admin")
@login_required
def dashboard():
    employees = get_all_employees()
    stats = get_stats()
    dep_stats = get_department_stats(employees)
    top = get_top_employees(employees, 5)
    values = [stats["new_count"], stats["work_count"], stats["clarify_count"], stats["closed_count"], stats["rejected_count"]]
    max_value = max(values) if max(values) > 0 else 1
    analytics = [
        ("Новые", stats["new_count"], round(stats["new_count"] / max_value * 100)),
        ("В работе", stats["work_count"], round(stats["work_count"] / max_value * 100)),
        ("На уточнении", stats["clarify_count"], round(stats["clarify_count"] / max_value * 100)),
        ("Закрытые", stats["closed_count"], round(stats["closed_count"] / max_value * 100)),
        ("Отказы", stats["rejected_count"], round(stats["rejected_count"] / max_value * 100)),
    ]
    top_html = "".join(
        f'<div class="mini-item"><div class="big-center">#{idx} {emp.get("fio", "—")}</div><div class="small">Закрыто дел: {emp.get("closed_cases_count", 0)} | Всего дел: {emp.get("cases_count", 0)}</div></div>'
        for idx, emp in enumerate(top, start=1)
    )
    content = f"""
    <div class="grid">
        <div class="card"><div>Новые обращения</div><div class="stat-number">{stats["new_count"]}</div></div>
        <div class="card"><div>В работе</div><div class="stat-number">{stats["work_count"]}</div></div>
        <div class="card"><div>Анкет на рассмотрении</div><div class="stat-number">{stats["hr_count"]}</div></div>
        <div class="card"><div>Заявок на доступ</div><div class="stat-number">{stats["access_new_count"]}</div></div>
        <div class="card"><div>Одобренных доступов</div><div class="stat-number">{stats["access_approved_count"]}</div></div>
        <div class="card"><div>Истекших испытательных</div><div class="stat-number">{stats["probation_count"]}</div></div>
    </div>
    <div class="row-3">
        <div class="card">
            <h3>📊 Быстрая аналитика</h3>
            {''.join([f'<div class="mini-item"><b>{label}</b><br>{value}</div>' for label, value, _ in analytics])}
        </div>
        <div class="card">
            <h3>🏢 Подразделения</h3>
            <div class="mini-item"><div class="big-center">СО</div><div class="small">Сотрудников: {dep_stats["so_count"]}</div></div>
            <div class="mini-item"><div class="big-center">ВСО</div><div class="small">Сотрудников: {dep_stats["vso_count"]}</div></div>
        </div>
        <div class="card">
            <h3>🏆 Топ сотрудников</h3>
            {top_html or '<div class="mini-item">Нет данных</div>'}
        </div>
    </div>
    """
    return render_page("Дашборд", content, active="dashboard")


@app.route("/access-requests")
@login_required
def access_requests():
    requests_list = get_recent_web_access_requests(200)
    rows = "".join(
        f"<tr><td>{item.get('id','')}</td><td>{item.get('fio','')}</td><td>{item.get('discord_id','')}</td><td>{item.get('department','')}</td><td>{item.get('position','')}</td><td>{item.get('status','')}</td><td>{item.get('created_at','')}</td><td><a href='/access-request/{item.get('id')}'>Открыть</a></td></tr>"
        for item in requests_list
    )
    content = f"""
    <div class="card">
        <h3>🛂 Заявки на доступ</h3>
        <table>
            <tr><th>ID</th><th>ФИО</th><th>Discord ID</th><th>Подразделение</th><th>Должность</th><th>Статус</th><th>Создано</th><th>Открыть</th></tr>
            {rows or '<tr><td colspan="8">Нет заявок</td></tr>'}
        </table>
    </div>
    """
    return render_page("Заявки на доступ", content, active="access_requests")


@app.route("/access-request/<int:request_id>")
@login_required
def access_request_card(request_id):
    item = get_web_access_request(request_id)
    if not item:
        return render_page("Заявка не найдена", "<div class='card'>Заявка не найдена.</div>", active="access_requests")

    actions = ""
    if item.get("status") == "Новая":
        actions = f"""
        <div class="toolbar">
            <form method="post" action="/access-request/{request_id}/approve"><button class="btn" type="submit">✅ Одобрить</button></form>
            <form method="post" action="/access-request/{request_id}/reject"><button class="btn red" type="submit">❌ Отклонить</button></form>
        </div>
        """
    password_block = f"<div class='box'><b>Выданный пароль:</b><br>{item.get('approved_password')}</div>" if item.get("approved_password") else ""
    content = f"""
    <div class="card">
        <h3>🛂 Заявка на доступ #{item.get("id")}</h3>
        {actions}
        <div class="kv">
            <div class="box"><b>ФИО:</b><br>{item.get("fio","—")}</div>
            <div class="box"><b>Discord ID:</b><br>{item.get("discord_id","—")}</div>
            <div class="box"><b>Подразделение:</b><br>{item.get("department","—")}</div>
            <div class="box"><b>Должность:</b><br>{item.get("position","—")}</div>
            <div class="box"><b>Статус:</b><br>{item.get("status","—")}</div>
            <div class="box"><b>Создано:</b><br>{item.get("created_at","—")}</div>
            <div class="box"><b>Проверил:</b><br>{item.get("reviewed_by_name") or "—"}</div>
            <div class="box"><b>Проверено:</b><br>{item.get("reviewed_at") or "—"}</div>
        </div>
        <div class="box" style="margin-bottom:14px;"><b>Причина запроса:</b><br><br>{item.get("reason") or "—"}</div>
        {password_block}
    </div>
    """
    return render_page(f"Заявка #{request_id}", content, active="access_requests")


@app.route("/access-request/<int:request_id>/approve", methods=["POST"])
@login_required
def approve_access_request_route(request_id):
    approve_web_access_request(request_id, reviewed_by=0, reviewed_by_name="WEB_PANEL")
    return redirect(f"/access-request/{request_id}?message=Заявка одобрена. Пароль отправлен ботом в ЛС и сохранён в карточке.")


@app.route("/access-request/<int:request_id>/reject", methods=["POST"])
@login_required
def reject_access_request_route(request_id):
    reject_web_access_request(request_id, reviewed_by=0, reviewed_by_name="WEB_PANEL")
    return redirect(f"/access-request/{request_id}?message=Заявка отклонена.")


@app.route("/web-users")
@login_required
def web_users():
    users = get_all_web_users(200)
    rows = "".join(
        f"<tr><td>{item.get('fio','')}</td><td>{item.get('discord_id','')}</td><td>{item.get('department','')}</td><td>{item.get('role','')}</td><td>{'Да' if item.get('is_active') else 'Нет'}</td><td>{item.get('created_at','')}</td></tr>"
        for item in users
    )
    content = f"""
    <div class="card">
        <h3>👥 Веб-сотрудники</h3>
        <table>
            <tr><th>ФИО</th><th>Discord ID</th><th>Подразделение</th><th>Роль</th><th>Активен</th><th>Создан</th></tr>
            {rows or '<tr><td colspan="6">Нет пользователей</td></tr>'}
        </table>
    </div>
    """
    return render_page("Веб-сотрудники", content, active="web_users")


@app.route("/leadership-inbox")
@login_required
def leadership_inbox():
    messages = leadership_get_all_messages()
    rows = ""
    for item in messages:
        attachment = "—"
        if item.get("attachment_stored_filename"):
            attachment = f"<a href='/admin/download/{item.get('attachment_stored_filename')}'>{item.get('attachment_filename')}</a>"
        rows += f"<tr><td>{item.get('fio') or '—'}</td><td>{item.get('discord_id','')}</td><td>{item.get('subject','')}</td><td>{item.get('status','')}</td><td>{item.get('created_at','')}</td><td>{attachment}</td><td>{(item.get('message','') or '')[:200]}</td></tr>"
    content = f"""
    <div class="card">
        <h3>📨 Обращения руководству</h3>
        <table>
            <tr><th>ФИО</th><th>Discord ID</th><th>Тема</th><th>Статус</th><th>Дата</th><th>Вложение</th><th>Текст</th></tr>
            {rows or '<tr><td colspan="7">Нет обращений</td></tr>'}
        </table>
    </div>
    """
    return render_page("Руководству", content, active="leadership")


@app.route("/admin/download/<filename>")
@login_required
def admin_download(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.route("/appeals")
@login_required
def appeals():
    all_appeals = get_recent_appeals(200)
    appeal_status = request.args.get("appeal_status", "").strip()
    appeal_department = request.args.get("appeal_department", "").strip()
    appeal_number = request.args.get("appeal_number", "").strip()
    appeal_priority = request.args.get("appeal_priority", "").strip()
    appeals_filtered = filter_appeals(all_appeals, appeal_status, appeal_department, appeal_number, appeal_priority)
    rows = "".join(
        f"<tr><td>{item.get('number','')}</td><td>{item.get('status','')}</td><td>{item.get('department','')}</td><td>{item.get('priority','')}</td><td>{item.get('created_at','')}</td><td><a href='/appeal/{item.get('number','')}'>Карточка</a></td><td><a href='/appeal/{item.get('number','')}/edit'>Редактировать</a></td></tr>"
        for item in appeals_filtered[:100]
    )
    content = f"""
    <div class="card">
        <h3>📨 Обращения</h3>
        <div class="toolbar">
            <form method="get" action="/appeals">
                <select name="appeal_status">
                    <option value="">Все статусы</option>
                    <option value="Принято" {"selected" if appeal_status == "Принято" else ""}>Принято</option>
                    <option value="В работе" {"selected" if appeal_status == "В работе" else ""}>В работе</option>
                    <option value="Требует уточнения" {"selected" if appeal_status == "Требует уточнения" else ""}>Требует уточнения</option>
                    <option value="Закрыто" {"selected" if appeal_status == "Закрыто" else ""}>Закрыто</option>
                    <option value="Отказано" {"selected" if appeal_status == "Отказано" else ""}>Отказано</option>
                    <option value="Архив" {"selected" if appeal_status == "Архив" else ""}>Архив</option>
                </select>
                <select name="appeal_department">
                    <option value="">Все подразделения</option>
                    <option value="СО" {"selected" if appeal_department == "СО" else ""}>СО</option>
                    <option value="ВСО" {"selected" if appeal_department == "ВСО" else ""}>ВСО</option>
                </select>
                <select name="appeal_priority">
                    <option value="">Все приоритеты</option>
                    <option value="Высокий" {"selected" if appeal_priority == "Высокий" else ""}>Высокий</option>
                    <option value="Обычный" {"selected" if appeal_priority == "Обычный" else ""}>Обычный</option>
                    <option value="Низкий" {"selected" if appeal_priority == "Низкий" else ""}>Низкий</option>
                </select>
                <input type="text" name="appeal_number" placeholder="Номер обращения" value="{appeal_number}">
                <button class="btn" type="submit">Применить фильтр</button>
            </form>
        </div>
        <table>
            <tr><th>Номер</th><th>Статус</th><th>Подразделение</th><th>Приоритет</th><th>Создано</th><th>Открыть</th><th>Ред.</th></tr>
            {rows or '<tr><td colspan="7">Нет данных</td></tr>'}
        </table>
    </div>
    """
    return render_page("Обращения", content, active="appeals")


@app.route("/appeal/<number>")
@login_required
def appeal_card(number):
    appeal = get_appeal_by_number(number)
    if not appeal:
        return render_page("Обращение не найдено", "<div class='card'>Обращение не найдено.</div>", active="appeals")
    history = get_appeal_history_for_page(number)
    history_html = "".join(
        f"<div class='timeline-item'><b>{row.get('action','—')}</b><br><span class='small'>{row.get('created_at','—')} | {row.get('actor_name') or 'Неизвестно'}</span><br><br>{row.get('details') or '—'}</div>"
        for row in history
    )
    content = f"""
    <div class="card">
        <h3>📨 Карточка обращения — {appeal.get("number", "")}</h3>
        <div class="kv">
            <div class="box"><b>Статус:</b><br>{appeal.get("status", "—")}</div>
            <div class="box"><b>Подразделение:</b><br>{appeal.get("department", "—")}</div>
            <div class="box"><b>Тип:</b><br>{appeal.get("appeal_type", "—")}</div>
            <div class="box"><b>Приоритет:</b><br>{appeal.get("priority", "—")}</div>
            <div class="box"><b>ФИО:</b><br>{appeal.get("fio", "—")}</div>
            <div class="box"><b>Контакт:</b><br>{appeal.get("contact", "—")}</div>
            <div class="box"><b>Discord ID заявителя:</b><br>{appeal.get("user_id", "—")}</div>
            <div class="box"><b>Создано:</b><br>{appeal.get("created_at", "—")}</div>
            <div class="box"><b>Исполнитель:</b><br>{appeal.get("assigned_to") or "—"}</div>
            <div class="box"><b>Принял:</b><br>{appeal.get("accepted_by") or "—"}</div>
            <div class="box"><b>Рабочий чат:</b><br>{appeal.get("work_channel_id") or "—"}</div>
            <div class="box"><b>Завершено:</b><br>{appeal.get("closed_at") or "—"}</div>
        </div>
        <div class="box" style="margin-bottom:14px;"><b>Описание:</b><br><br>{appeal.get("description") or "—"}</div>
        <div class="box" style="margin-bottom:14px;"><b>Уточнение:</b><br><br>{appeal.get("clarification_text") or "—"}</div>
        <div class="box" style="margin-bottom:14px;"><b>Ответ заявителя:</b><br><br>{appeal.get("citizen_reply_text") or "—"}</div>
        <div class="box" style="margin-bottom:14px;"><b>Итог / причина:</b><br><br>{appeal.get("resolution_text") or "—"}</div>
    </div>
    <div class="card"><h3>🕒 История обращения</h3>{history_html or "<div class='timeline-item'>История пуста</div>"}</div>
    """
    return render_page(f"Обращение {number}", content, active="appeals")


@app.route("/appeal/<number>/edit", methods=["GET", "POST"])
@login_required
def appeal_edit(number):
    appeal = get_appeal_by_number(number)
    if not appeal:
        return render_page("Обращение не найдено", "<div class='card'>Обращение не найдено.</div>", active="appeals")
    employees = get_all_employees()
    if request.method == "POST":
        update_appeal_from_web(number, request.form)
        return redirect(f"/appeal/{number}?message=Обращение обновлено")

    options = "<option value=''>Не назначен</option>"
    for emp in employees:
        selected = "selected" if str(emp.get("discord_id")) == str(appeal.get("assigned_to") or "") else ""
        options += f"<option value='{emp.get('discord_id')}' {selected}>{emp.get('fio')} ({emp.get('discord_id')})</option>"

    content = f"""
    <div class="card">
        <h3>✏️ Редактирование обращения — {appeal.get("number","")}</h3>
        <form method="post">
            <select name="status">
                <option value="Принято" {"selected" if appeal.get("status") == "Принято" else ""}>Принято</option>
                <option value="В работе" {"selected" if appeal.get("status") == "В работе" else ""}>В работе</option>
                <option value="Требует уточнения" {"selected" if appeal.get("status") == "Требует уточнения" else ""}>Требует уточнения</option>
                <option value="Закрыто" {"selected" if appeal.get("status") == "Закрыто" else ""}>Закрыто</option>
                <option value="Отказано" {"selected" if appeal.get("status") == "Отказано" else ""}>Отказано</option>
                <option value="Архив" {"selected" if appeal.get("status") == "Архив" else ""}>Архив</option>
            </select>
            <select name="department">
                <option value="СО" {"selected" if appeal.get("department") == "СО" else ""}>СО</option>
                <option value="ВСО" {"selected" if appeal.get("department") == "ВСО" else ""}>ВСО</option>
            </select>
            <select name="priority">
                <option value="Высокий" {"selected" if appeal.get("priority") == "Высокий" else ""}>Высокий</option>
                <option value="Обычный" {"selected" if appeal.get("priority") == "Обычный" else ""}>Обычный</option>
                <option value="Низкий" {"selected" if appeal.get("priority") == "Низкий" else ""}>Низкий</option>
            </select>
            <select name="assigned_to">{options}</select>
            <textarea name="clarification_text" placeholder="Текст уточнения">{appeal.get("clarification_text") or ""}</textarea>
            <textarea name="resolution_text" placeholder="Итог / причина">{appeal.get("resolution_text") or ""}</textarea>
            <button class="btn" type="submit">Сохранить изменения</button>
        </form>
    </div>
    """
    return render_page(f"Редактирование {number}", content, active="appeals")


@app.route("/employees")
@login_required
def employees():
    all_employees = get_all_employees()
    search_value = request.args.get("search_discord_id", "").strip()
    employee_department = request.args.get("employee_department", "").strip()
    employee_fio = request.args.get("employee_fio", "").strip()
    employee_status = request.args.get("employee_status", "").strip()

    searched_employee = search_employee_by_discord_id(int(search_value)) if search_value.isdigit() else None
    employees_filtered = filter_employees(all_employees, employee_department, employee_fio, employee_status)

    rows = "".join(
        f"<tr><td>{item.get('fio','')}</td><td>{item.get('discord_id','')}</td><td>{item.get('department','')}</td><td>{item.get('position','')}</td><td>{item.get('rank_name','')}</td><td>{item.get('status','')}</td><td>{item.get('cases_count',0)}</td><td>{item.get('closed_cases_count',0)}</td><td><a href='/employee/{item.get('discord_id',0)}'>Карточка</a></td><td><a href='/employee/{item.get('discord_id',0)}/edit'>Ред.</a></td></tr>"
        for item in employees_filtered[:150]
    )

    search_block = ""
    if searched_employee:
        search_block = f"""
        <div class="box">
            <b>{searched_employee.get("fio", "—")}</b><br><br>
            Discord ID: {searched_employee.get("discord_id", "—")}<br>
            Подразделение: {searched_employee.get("department", "—")}<br>
            Должность: {searched_employee.get("position", "—")}<br>
            Звание: {searched_employee.get("rank_name", "—")}<br>
            Статус: {searched_employee.get("status", "—")}<br>
            Дел: {searched_employee.get("cases_count", 0)}<br>
            Закрыто: {searched_employee.get("closed_cases_count", 0)}<br>
            Выговоры: {searched_employee.get("warnings_count", 0)}<br>
            Награды: {searched_employee.get("rewards_count", 0)}<br>
            Примечания: {searched_employee.get("notes") or "—"}
        </div>
        """
    elif search_value:
        search_block = "<div class='box'>Сотрудник не найден.</div>"

    content = f"""
    <div class="row-2">
        <div class="card">
            <h3>🔎 Поиск сотрудника по Discord ID</h3>
            <form method="get" action="/employees">
                <input type="text" name="search_discord_id" placeholder="Введите Discord ID" value="{search_value}">
                <button class="btn" type="submit">Найти</button>
            </form>
            {search_block}
        </div>
        <div class="card">
            <h3>👤 Создание / обновление карточки</h3>
            <form method="post" action="/employee/save">
                <input type="text" name="discord_id" placeholder="Discord ID" required>
                <input type="text" name="fio" placeholder="ФИО" required>
                <select name="department" required><option value="СО">СО</option><option value="ВСО">ВСО</option></select>
                <input type="text" name="position" placeholder="Должность" required>
                <input type="text" name="rank_name" placeholder="Звание" required>
                <input type="text" name="status" placeholder="Статус" required>
                <textarea name="notes" placeholder="Примечания"></textarea>
                <button class="btn" type="submit">Сохранить карточку</button>
            </form>
        </div>
    </div>
    <div class="card">
        <h3>👥 Сотрудники</h3>
        <div class="toolbar">
            <form method="get" action="/employees">
                <select name="employee_department">
                    <option value="">Все подразделения</option>
                    <option value="СО" {"selected" if employee_department == "СО" else ""}>СО</option>
                    <option value="ВСО" {"selected" if employee_department == "ВСО" else ""}>ВСО</option>
                </select>
                <input type="text" name="employee_fio" placeholder="Поиск по ФИО" value="{employee_fio}">
                <input type="text" name="employee_status" placeholder="Статус" value="{employee_status}">
                <button class="btn" type="submit">Применить фильтр</button>
            </form>
        </div>
        <table>
            <tr><th>ФИО</th><th>Discord ID</th><th>Подразделение</th><th>Должность</th><th>Звание</th><th>Статус</th><th>Дел</th><th>Закрыто</th><th>Открыть</th><th>Ред.</th></tr>
            {rows or '<tr><td colspan="10">Нет данных</td></tr>'}
        </table>
    </div>
    """
    return render_page("Кадры", content, active="employees")


@app.route("/employee/<int:discord_id>")
@login_required
def employee_card(discord_id):
    employee = search_employee_by_discord_id(discord_id)
    if not employee:
        return render_page("Сотрудник не найден", "<div class='card'>Сотрудник не найден.</div>", active="employees")
    content = f"""
    <div class="card">
        <h3>👤 Карточка сотрудника — {employee.get("fio", "")}</h3>
        <div class="kv">
            <div class="box"><b>Discord ID:</b><br>{employee.get("discord_id", "—")}</div>
            <div class="box"><b>Подразделение:</b><br>{employee.get("department", "—")}</div>
            <div class="box"><b>Должность:</b><br>{employee.get("position", "—")}</div>
            <div class="box"><b>Звание:</b><br>{employee.get("rank_name", "—")}</div>
            <div class="box"><b>Статус:</b><br>{employee.get("status", "—")}</div>
            <div class="box"><b>Дата вступления:</b><br>{employee.get("joined_at", "—")}</div>
            <div class="box"><b>Испытательный срок до:</b><br>{employee.get("probation_until") or "—"}</div>
            <div class="box"><b>Всего дел:</b><br>{employee.get("cases_count", 0)}</div>
            <div class="box"><b>Закрыто дел:</b><br>{employee.get("closed_cases_count", 0)}</div>
            <div class="box"><b>Выговоры:</b><br>{employee.get("warnings_count", 0)}</div>
            <div class="box"><b>Повышения:</b><br>{employee.get("promotions_count", 0)}</div>
            <div class="box"><b>Награды:</b><br>{employee.get("rewards_count", 0)}</div>
        </div>
        <div class="box"><b>Примечания:</b><br><br>{employee.get("notes") or "—"}</div>
    </div>
    """
    return render_page(f"Сотрудник {employee.get('fio', '')}", content, active="employees")


@app.route("/employee/<int:discord_id>/edit", methods=["GET", "POST"])
@login_required
def employee_edit(discord_id):
    employee = search_employee_by_discord_id(discord_id)
    if not employee:
        return render_page("Сотрудник не найден", "<div class='card'>Сотрудник не найден.</div>", active="employees")
    if request.method == "POST":
        update_employee_from_web(discord_id, request.form)
        return redirect(f"/employee/{discord_id}?message=Карточка сотрудника обновлена")

    content = f"""
    <div class="card">
        <h3>✏️ Редактирование сотрудника — {employee.get("fio","")}</h3>
        <form method="post">
            <input type="text" name="fio" value="{employee.get("fio","")}" required>
            <select name="department" required>
                <option value="СО" {"selected" if employee.get("department") == "СО" else ""}>СО</option>
                <option value="ВСО" {"selected" if employee.get("department") == "ВСО" else ""}>ВСО</option>
            </select>
            <input type="text" name="position" value="{employee.get("position","")}" required>
            <input type="text" name="rank_name" value="{employee.get("rank_name","")}" required>
            <input type="text" name="status" value="{employee.get("status","")}" required>
            <textarea name="notes">{employee.get("notes") or ""}</textarea>
            <button class="btn" type="submit">Сохранить изменения</button>
        </form>
    </div>
    """
    return render_page(f"Редактирование {employee.get('fio','')}", content, active="employees")


@app.route("/employee/save", methods=["POST"])
@login_required
def save_employee():
    discord_id = int(request.form["discord_id"].strip())
    upsert_employee_from_web(
        discord_id=discord_id,
        fio=request.form["fio"].strip(),
        department=request.form["department"].strip(),
        position=request.form["position"].strip(),
        rank_name=request.form["rank_name"].strip(),
        status=request.form["status"].strip(),
        notes=request.form.get("notes", "").strip(),
    )
    return redirect("/employees?message=Карточка сотрудника сохранена")


@app.route("/analytics")
@login_required
def analytics():
    employees = get_all_employees()
    status_chart = save_status_chart()
    employee_chart = save_employee_chart(employees)
    department_chart = save_department_chart(employees)
    content = f"""
    <div class="row-2">
        <div class="card"><h3>📊 Статусы обращений</h3><img src="/static/{status_chart}" alt="Статусы обращений" style="max-width:100%"></div>
        <div class="card"><h3>🏆 Топ сотрудников</h3><img src="/static/{employee_chart}" alt="Топ сотрудников" style="max-width:100%"></div>
    </div>
    <div class="card"><h3>🏢 Подразделения</h3><img src="/static/{department_chart}" alt="Подразделения" style="max-width:100%"></div>
    """
    return render_page("Аналитика", content, active="analytics")


@app.route("/discipline")
@login_required
def discipline():
    fio = request.args.get("fio", "").strip()
    action_type = request.args.get("action_type", "").strip()
    records = filter_discipline(load_discipline_records(200), fio, action_type)
    rows = "".join(
        f"<tr><td>{item.get('number','')}</td><td>{item.get('fio','')}</td><td>{item.get('action_type','')}</td><td>{item.get('reason','')}</td><td>{item.get('issued_by_name','')}</td><td>{item.get('created_at','')}</td></tr>"
        for item in records
    )
    content = f"""
    <div class="card">
        <h3>⚖️ Дисциплина</h3>
        <div class="toolbar">
            <form method="get" action="/discipline">
                <input type="text" name="fio" placeholder="Поиск по ФИО" value="{fio}">
                <input type="text" name="action_type" placeholder="Тип меры" value="{action_type}">
                <button class="btn" type="submit">Применить фильтр</button>
            </form>
        </div>
        <table>
            <tr><th>Номер</th><th>Сотрудник</th><th>Тип</th><th>Причина</th><th>Кто выдал</th><th>Дата</th></tr>
            {rows or '<tr><td colspan="6">Нет записей</td></tr>'}
        </table>
    </div>
    """
    return render_page("Дисциплина", content, active="discipline")


@app.route("/backup", methods=["POST"])
@login_required
def make_backup():
    path = backup_database()
    return redirect(f"/admin?message=Бэкап создан: {path}")


# =========================
# STAFF ROUTES
# =========================

@app.route("/staff/dashboard")
@staff_login_required
def staff_dashboard():
    user = session.get("staff_user", {})
    docs = staff_get_documents(user.get("discord_id"))
    msgs = staff_get_messages(user.get("discord_id"))
    content = f"""
    <div class="grid">
        <div class="card"><div>Мои документы</div><div class="stat-number">{len(docs)}</div></div>
        <div class="card"><div>Сообщения руководству</div><div class="stat-number">{len(msgs)}</div></div>
        <div class="card"><div>Подразделение</div><div class="stat-number" style="font-size:24px;">{user.get("department","—")}</div></div>
        <div class="card"><div>Discord ID</div><div class="stat-number" style="font-size:20px;">{user.get("discord_id","—")}</div></div>
    </div>
    <div class="row-2">
        <div class="card">
            <h3>👤 Ваш профиль</h3>
            <div class="kv">
                <div class="box"><b>ФИО:</b><br>{user.get("fio","—")}</div>
                <div class="box"><b>Подразделение:</b><br>{user.get("department","—")}</div>
                <div class="box"><b>Discord ID:</b><br>{user.get("discord_id","—")}</div>
                <div class="box"><b>Роль:</b><br>{user.get("role","employee")}</div>
            </div>
        </div>
        <div class="card">
            <h3>⚡ Быстрые действия</h3>
            <p><a class="btn" href="/staff/upload">⬆️ Загрузить документ</a></p>
            <p><a class="btn secondary" href="/staff/documents">📂 Мои документы</a></p>
            <p><a class="btn secondary" href="/staff/leadership">📨 Написать руководству</a></p>
            <p><a class="btn secondary" href="/staff/change-password">🔐 Сменить пароль</a></p>
        </div>
    </div>
    """
    return render_staff_page("Главная", content, active="dashboard")


@app.route("/staff/documents")
@staff_login_required
def staff_documents():
    user = session.get("staff_user", {})
    docs = staff_get_documents(user.get("discord_id"))
    rows = "".join(
        f"<tr><td>{item.get('original_filename','')}</td><td>{item.get('file_ext','')}</td><td>{item.get('description') or '—'}</td><td>{item.get('created_at','')}</td><td><a href='/staff/download/{item.get('stored_filename')}'>Скачать</a></td></tr>"
        for item in docs
    )
    content = f"""
    <div class="card">
        <h3>📂 Мои документы</h3>
        <table>
            <tr><th>Файл</th><th>Тип</th><th>Описание</th><th>Дата</th><th>Действие</th></tr>
            {rows or '<tr><td colspan="5">Документы ещё не загружались</td></tr>'}
        </table>
    </div>
    """
    return render_staff_page("Мои документы", content, active="documents")


@app.route("/staff/upload", methods=["GET", "POST"])
@staff_login_required
def staff_upload():
    user = session.get("staff_user", {})
    error = ""
    success = ""
    if request.method == "POST":
        description = request.form.get("description", "").strip()
        file = request.files.get("file")
        if not file or not file.filename:
            error = "Выберите файл."
        elif not allowed_file(file.filename):
            error = "Разрешены только .doc, .docx, .pdf, .png"
        else:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                error = f"Файл слишком большой. Максимум {MAX_UPLOAD_MB} МБ."
            else:
                original_name, stored_name = save_uploaded_file(file, f"emp_{user.get('discord_id')}")
                ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else ""
                staff_add_document(user.get("discord_id"), original_name, stored_name, ext, description)
                success = "Документ загружен."
    content = f"""
    <div class="card">
        <h3>⬆️ Загрузка документа</h3>
        {f'<div class="message">{success}</div>' if success else ''}
        {f'<div class="message" style="background:rgba(220,38,38,.16);">{error}</div>' if error else ''}
        <form method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept=".doc,.docx,.pdf,.png" required>
            <textarea name="description" placeholder="Краткое описание документа"></textarea>
            <button class="btn" type="submit">Загрузить</button>
        </form>
        <div class="box"><b>Разрешены:</b> .doc, .docx, .pdf, .png<br><b>Максимум:</b> {MAX_UPLOAD_MB} МБ</div>
    </div>
    """
    return render_staff_page("Загрузка документа", content, active="upload")


@app.route("/staff/download/<filename>")
@staff_login_required
def staff_download(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.route("/staff/leadership", methods=["GET", "POST"])
@staff_login_required
def staff_leadership():
    user = session.get("staff_user", {})
    error = ""
    success = ""
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message_text = request.form.get("message", "").strip()
        file = request.files.get("file")

        if not subject or not message_text:
            error = "Заполните тему и сообщение."
        else:
            original_name = None
            stored_name = None
            if file and file.filename:
                if not allowed_file(file.filename):
                    error = "Разрешены только .doc, .docx, .pdf, .png"
                else:
                    file.seek(0, os.SEEK_END)
                    size = file.tell()
                    file.seek(0)
                    if size > MAX_UPLOAD_MB * 1024 * 1024:
                        error = f"Файл слишком большой. Максимум {MAX_UPLOAD_MB} МБ."
                    else:
                        original_name, stored_name = save_uploaded_file(file, f"lead_{user.get('discord_id')}")
            if not error:
                staff_add_leadership_message(
                    user.get("discord_id"),
                    user.get("fio"),
                    subject,
                    message_text,
                    original_name,
                    stored_name,
                )
                success = "Сообщение отправлено руководству."

    msgs = staff_get_messages(user.get("discord_id"))
    rows = ""
    for item in msgs[:20]:
        attachment = "—"
        if item.get("attachment_stored_filename"):
            attachment = f"<a href='/staff/download/{item.get('attachment_stored_filename')}'>{item.get('attachment_filename')}</a>"
        rows += f"<tr><td>{item.get('subject','')}</td><td>{item.get('status','')}</td><td>{item.get('created_at','')}</td><td>{attachment}</td></tr>"
    content = f"""
    <div class="row-2">
        <div class="card">
            <h3>📨 Новое сообщение руководству</h3>
            {f'<div class="message">{success}</div>' if success else ''}
            {f'<div class="message" style="background:rgba(220,38,38,.16);">{error}</div>' if error else ''}
            <form method="post" enctype="multipart/form-data">
                <input type="text" name="subject" placeholder="Тема обращения" required>
                <textarea name="message" placeholder="Текст обращения" required></textarea>
                <input type="file" name="file" accept=".doc,.docx,.pdf,.png">
                <button class="btn" type="submit">Отправить</button>
            </form>
        </div>
        <div class="card">
            <h3>📋 Мои обращения</h3>
            <table>
                <tr><th>Тема</th><th>Статус</th><th>Дата</th><th>Вложение</th></tr>
                {rows or '<tr><td colspan="4">Обращений пока нет</td></tr>'}
            </table>
        </div>
    </div>
    """
    return render_staff_page("Руководству", content, active="leadership")


@app.route("/staff/change-password", methods=["GET", "POST"])
@staff_login_required
def staff_change_password():
    user = session.get("staff_user", {})
    error = ""
    success = ""
    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        auth_user = authenticate_web_user(user.get("discord_id"), old_password)
        if not auth_user:
            error = "Старый пароль неверный."
        elif len(new_password) < 6:
            error = "Новый пароль должен быть не короче 6 символов."
        elif new_password != confirm_password:
            error = "Подтверждение пароля не совпадает."
        else:
            staff_update_password(user.get("discord_id"), new_password)
            session["staff_user"] = get_web_user_by_discord_id(user.get("discord_id")) or user
            success = "Пароль обновлён."
    content = f"""
    <div class="card">
        <h3>🔐 Смена пароля</h3>
        {f'<div class="message">{success}</div>' if success else ''}
        {f'<div class="message" style="background:rgba(220,38,38,.16);">{error}</div>' if error else ''}
        <form method="post">
            <input type="password" name="old_password" placeholder="Старый пароль" required>
            <input type="password" name="new_password" placeholder="Новый пароль" required>
            <input type="password" name="confirm_password" placeholder="Подтвердите новый пароль" required>
            <button class="btn" type="submit">Сохранить новый пароль</button>
        </form>
    </div>
    """
    return render_staff_page("Смена пароля", content, active="password")


if __name__ == "__main__":
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
