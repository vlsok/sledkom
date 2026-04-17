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


def init_staff_section_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS employee_documents (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    file_ext TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    description TEXT
                )
                """
            )
            cur.execute(
                """
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
                """
            )
        conn.commit()


init_staff_section_tables()


def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file_storage, prefix: str) -> tuple[str, str]:
    original_name = file_storage.filename or "file"
    ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else ""
    stored_name = f"{prefix}_{uuid.uuid4().hex}.{ext}" if ext else f"{prefix}_{uuid.uuid4().hex}"
    file_storage.save(UPLOAD_DIR / stored_name)
    return original_name, stored_name


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


def load_discipline_records(limit: int = 200):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM discipline_records ORDER BY id DESC LIMIT %s", (limit,))
            return [dict(x) for x in cur.fetchall()]


def get_appeal_history_for_page(number: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeal_history WHERE appeal_number = %s ORDER BY id DESC LIMIT 30", (number,))
            return [dict(x) for x in cur.fetchall()]


def add_web_history(appeal_number: str, action: str, details: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO appeal_history (appeal_number, action, actor_id, actor_name, details, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (appeal_number, action, 0, "WEB_PANEL", details, now_str()),
            )
        conn.commit()


def filter_discipline(records, fio="", action_type=""):
    result = records
    if fio:
        result = [x for x in result if fio.lower() in (x.get("fio") or "").lower()]
    if action_type:
        result = [x for x in result if action_type.lower() in (x.get("action_type") or "").lower()]
    return result


def get_employee_by_id_for_page(discord_id: int):
    return search_employee_by_discord_id(discord_id)


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


def filter_employees(employees, department="", fio="", status=""):
    result = employees
    if department:
        result = [x for x in result if (x.get("department") or "") == department]
    if fio:
        result = [x for x in result if fio.lower() in (x.get("fio") or "").lower()]
    if status:
        result = [x for x in result if status.lower() in (x.get("status") or "").lower()]
    return result


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
    so_count = len([x for x in employees if x.get("department") == "СО"])
    vso_count = len([x for x in employees if x.get("department") == "ВСО"])
    return {"so_count": so_count, "vso_count": vso_count}


def get_top_employees(employees, limit=5):
    return sorted(
        employees,
        key=lambda x: (x.get("closed_cases_count", 0), x.get("cases_count", 0)),
        reverse=True,
    )[:limit]


def save_status_chart():
    stats = get_stats()
    labels = ["Новые", "В работе", "Уточнение", "Закрытые", "Отказы"]
    values = [stats["new_count"], stats["work_count"], stats["clarify_count"], stats["closed_count"], stats["rejected_count"]]
    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.title("Статусы обращений")
    plt.tight_layout()
    chart_path = STATIC_DIR / "appeals_status_chart.png"
    plt.savefig(chart_path, dpi=140)
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
    chart_path = STATIC_DIR / "employees_top_chart.png"
    plt.savefig(chart_path, dpi=140)
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
    chart_path = STATIC_DIR / "departments_chart.png"
    plt.savefig(chart_path, dpi=140)
    plt.close()
    return "departments_chart.png"


def update_appeal_from_web(number: str, form: dict):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE appeals
                SET status = %s, department = %s, priority = %s, assigned_to = %s,
                    clarification_text = %s, resolution_text = %s, updated_at = %s
                WHERE number = %s
                """,
                (
                    form.get("status", "").strip(),
                    form.get("department", "").strip(),
                    form.get("priority", "").strip(),
                    int(form["assigned_to"]) if form.get("assigned_to", "").strip().isdigit() else None,
                    form.get("clarification_text", "").strip() or None,
                    form.get("resolution_text", "").strip() or None,
                    now_str(),
                    number,
                ),
            )
        conn.commit()
    add_web_history(number, "Изменение через WEB_PANEL", f"Статус={form.get('status','')} | Подразделение={form.get('department','')} | Приоритет={form.get('priority','')}")


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


def render_page(title: str, content: str, active: str = "dashboard"):
    message = request.args.get("message", "")
    return render_template_string(BASE_ADMIN_TEMPLATE, title=title, content=content, active=active, message=message)


def render_staff_page(title: str, content: str, active: str = "dashboard"):
    message = request.args.get("message", "")
    user = session.get("staff_user", {})
    return render_template_string(BASE_STAFF_TEMPLATE, title=title, content=content, active=active, message=message, user=user)


def staff_get_documents(discord_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM employee_documents WHERE discord_id = %s ORDER BY id DESC", (discord_id,))
            return [dict(row) for row in cur.fetchall()]


def staff_add_document(discord_id: int, original_filename: str, stored_filename: str, file_ext: str, description: str = ""):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO employee_documents (discord_id, original_filename, stored_filename, file_ext, created_at, description) VALUES (%s, %s, %s, %s, %s, %s)",
                (discord_id, original_filename, stored_filename, file_ext, now_str(), description),
            )
        conn.commit()


def staff_add_leadership_message(discord_id: int, fio: str, subject: str, message_text: str, attachment_filename: str = None, attachment_stored_filename: str = None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO leadership_messages (discord_id, fio, subject, message, status, created_at, attachment_filename, attachment_stored_filename) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (discord_id, fio, subject, message_text, "Новая", now_str(), attachment_filename, attachment_stored_filename),
            )
        conn.commit()


def staff_get_messages(discord_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM leadership_messages WHERE discord_id = %s ORDER BY id DESC", (discord_id,))
            return [dict(row) for row in cur.fetchall()]


def leadership_get_all_messages():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM leadership_messages ORDER BY id DESC LIMIT 300")
            return [dict(row) for row in cur.fetchall()]


def staff_update_password(discord_id: int, new_password: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE web_users SET password = %s, password_hash = %s, updated_at = %s WHERE discord_id = %s", (new_password, new_password, now_str(), discord_id))
        conn.commit()


BASE_ADMIN_TEMPLATE = """
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }}</title>
    <style>
        :root { --bg1:#08111f; --bg2:#0f172a; --bg3:#111827; --text:#e5e7eb; --muted:#94a3b8; --line:#334155; }
        * { box-sizing:border-box; } body { margin:0; font-family:Arial,sans-serif; color:var(--text); background:linear-gradient(135deg,var(--bg1),var(--bg2),var(--bg3)); }
        .layout { display:grid; grid-template-columns:280px 1fr; min-height:100vh; }
        .sidebar { background:rgba(10,16,30,.88); padding:24px 18px; border-right:1px solid rgba(148,163,184,.08); }
        .nav { display:grid; gap:10px; } .nav a { display:block; padding:14px; border-radius:14px; color:#dbeafe; text-decoration:none; }
        .nav a.active,.nav a:hover { background:rgba(37,99,235,.18); }
        .main { padding:28px; } .topbar { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:20px; flex-wrap:wrap; }
        .btn { display:inline-block; padding:11px 16px; border:none; border-radius:12px; background:#2563eb; color:white; font-weight:bold; cursor:pointer; text-decoration:none; }
        .btn.secondary { background:#334155; } .btn.red { background:#b91c1c; }
        .message { padding:14px 16px; border-radius:14px; background:rgba(37,99,235,.18); border:1px solid rgba(147,197,253,.20); margin-bottom:20px; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }
        .card { background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98)); border:1px solid rgba(148,163,184,.08); border-radius:20px; padding:18px; margin-bottom:20px; }
        .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:24px; } .row-3 { display:grid; grid-template-columns:1.2fr .8fr .8fr; gap:18px; margin-bottom:24px; }
        .stat-number { font-size:32px; font-weight:bold; margin-top:8px; }
        table { width:100%; border-collapse:collapse; } th, td { padding:12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; } th { background:#0d1728; color:#cbd5e1; }
        input, select, textarea { width:100%; padding:11px 12px; border-radius:12px; border:1px solid #475569; background:#0f172a; color:white; margin-bottom:12px; }
        textarea { min-height:100px; resize:vertical; } .kv { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }
        .box,.mini-item { background:#0f172a; border:1px solid rgba(148,163,184,.08); border-radius:14px; padding:14px; } .mini-list,.chart { display:grid; gap:10px; }
        .bar-row { display:grid; grid-template-columns:160px 1fr 40px; gap:10px; align-items:center; } .bar { height:12px; border-radius:999px; background:#0f172a; overflow:hidden; }
        .bar>span { display:block; height:100%; border-radius:999px; background:linear-gradient(90deg,#2563eb,#60a5fa); }
        @media (max-width:1100px) { .layout{grid-template-columns:1fr;} .row-2,.row-3,.kv{grid-template-columns:1fr;} }
    </style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
  <div style="margin-bottom:26px;"><h1 style="margin:0 0 8px 0;font-size:22px;">👑 СУ СК</h1><p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.45;">Внутренняя панель управления<br>Следственным управлением</p></div>
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
  <div class="topbar"><div><h2 style="margin:0;font-size:26px;">{{ title }}</h2></div><div><form method="post" action="/backup" style="margin:0;display:inline;"><button class="btn" type="submit">💾 Бэкап базы</button></form> <a class="btn secondary" href="/admin">↻ Обновить</a></div></div>
  {% if message %}<div class="message">{{ message }}</div>{% endif %}
  <div class="page-content">{{ content|safe }}</div>
</main>
</div>
</body>
</html>
"""

BASE_STAFF_TEMPLATE = """
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }}</title>
    <style>
        :root { --bg1:#08111f; --bg2:#0f172a; --bg3:#111827; --text:#e5e7eb; --muted:#94a3b8; --line:#334155; }
        * { box-sizing:border-box; } body { margin:0; font-family:Arial,sans-serif; color:var(--text); background:linear-gradient(135deg,var(--bg1),var(--bg2),var(--bg3)); }
        .layout { display:grid; grid-template-columns:280px 1fr; min-height:100vh; }
        .sidebar { background:rgba(10,16,30,.88); padding:24px 18px; border-right:1px solid rgba(148,163,184,.08); }
        .nav { display:grid; gap:10px; } .nav a { display:block; padding:14px; border-radius:14px; color:#dbeafe; text-decoration:none; }
        .nav a.active,.nav a:hover { background:rgba(37,99,235,.18); }
        .main { padding:28px; } .topbar { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:20px; flex-wrap:wrap; }
        .btn { display:inline-block; padding:11px 16px; border:none; border-radius:12px; background:#2563eb; color:white; font-weight:bold; cursor:pointer; text-decoration:none; }
        .btn.secondary { background:#334155; }
        .message { padding:14px 16px; border-radius:14px; background:rgba(37,99,235,.18); border:1px solid rgba(147,197,253,.20); margin-bottom:20px; }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }
        .card { background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98)); border:1px solid rgba(148,163,184,.08); border-radius:20px; padding:18px; margin-bottom:20px; }
        .row-2 { display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:24px; } .stat-number { font-size:28px; font-weight:bold; margin-top:8px; }
        table { width:100%; border-collapse:collapse; } th, td { padding:12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; } th { background:#0d1728; color:#cbd5e1; }
        input, select, textarea { width:100%; padding:11px 12px; border-radius:12px; border:1px solid #475569; background:#0f172a; color:white; margin-bottom:12px; }
        textarea { min-height:120px; resize:vertical; } .kv { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px; }
        .box,.mini-item { background:#0f172a; border:1px solid rgba(148,163,184,.08); border-radius:14px; padding:14px; } .mini-list{display:grid;gap:10px;}
        @media (max-width:1100px) { .layout{grid-template-columns:1fr;} .row-2,.kv{grid-template-columns:1fr;} }
    </style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
  <div style="margin-bottom:26px;"><h1 style="margin:0 0 8px 0;font-size:22px;">👤 Кабинет сотрудника</h1><p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.45;">{{ user.get('fio','Сотрудник') }}<br>{{ user.get('department','—') }}</p></div>
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
  <div class="topbar"><div><h2 style="margin:0;font-size:26px;">{{ title }}</h2></div><div><a class="btn secondary" href="/staff/dashboard">↻ Обновить</a></div></div>
  {% if message %}<div class="message">{{ message }}</div>{% endif %}
  <div class="page-content">{{ content|safe }}</div>
</main>
</div>
</body>
</html>
"""


@app.route("/")
def public_index():
    return render_template_string("""
    <!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>СУ СК — Портал</title>
    <style>
        body{margin:0;font-family:Arial,sans-serif;color:#e5e7eb;background:linear-gradient(135deg,#08111f,#0f172a,#111827);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
        .shell{width:100%;max-width:1100px}.hero{text-align:center;margin-bottom:26px}.hero h1{font-size:40px;margin:0 0 12px 0}.hero p{margin:0 auto;max-width:720px;color:#94a3b8;line-height:1.6;font-size:16px}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}.card{background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98));border:1px solid rgba(148,163,184,.08);border-radius:24px;padding:24px}
        .card h3{margin:0 0 12px 0;font-size:22px}.card p{margin:0 0 20px 0;color:#94a3b8;line-height:1.6;min-height:90px}.btn{display:inline-block;padding:12px 18px;border-radius:14px;background:#2563eb;color:white;text-decoration:none;font-weight:bold}
    </style></head><body>
    <div class="shell"><div class="hero"><h1>👑 СУ СК — Веб-портал</h1><p>Единый портал для руководства и сотрудников.</p></div>
    <div class="grid">
      <div class="card"><h3>🔐 Мой раздел</h3><p>Закрытая административная панель руководства.</p><a class="btn" href="/login">Открыть раздел</a></div>
      <div class="card"><h3>👥 Раздел сотрудников</h3><p>Личный кабинет сотрудника: вход, документы, сообщения руководству и смена пароля.</p><a class="btn" href="/staff-login">Перейти</a></div>
      <div class="card"><h3>🛂 Запрос доступа</h3><p>Подача заявки на доступ к кабинету сотрудника.</p><a class="btn" href="/request-access">Открыть форму</a></div>
    </div></div></body></html>
    """)


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
                        cur.execute("INSERT INTO web_access_requests (discord_id, fio, department, position, reason, status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)", (discord_id, fio, department, position, reason, "Новая", now_str()))
                    conn.commit()
                success = "Заявка на доступ отправлена."
    return render_template_string("""
    <!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Запрос доступа</title>
    <style>
        body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(135deg,#08111f,#0f172a,#111827);color:#e5e7eb;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
        .card{width:100%;max-width:680px;background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98));border:1px solid rgba(148,163,184,.08);border-radius:24px;padding:26px}.error,.success{margin-bottom:12px;padding:12px;border-radius:12px}.error{background:rgba(220,38,38,.16);color:#fecaca}.success{background:rgba(22,163,74,.16);color:#bbf7d0}
        input,select,textarea{width:100%;padding:12px;border-radius:12px;border:1px solid #475569;background:#0f172a;color:white;margin-bottom:12px;box-sizing:border-box} textarea{min-height:110px;resize:vertical}.actions{display:flex;gap:10px;flex-wrap:wrap}
        button,a.btn{display:inline-block;padding:12px 16px;border:none;border-radius:12px;background:#2563eb;color:white;text-decoration:none;font-weight:bold;cursor:pointer} a.secondary{background:#334155}
    </style></head><body><div class="card"><h1>🛂 Запрос доступа сотрудника</h1>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}
    <form method="post"><input type="text" name="discord_id" placeholder="Discord ID" required><input type="text" name="fio" placeholder="ФИО" required><select name="department" required><option value="СО">СО</option><option value="ВСО">ВСО</option></select><input type="text" name="position" placeholder="Должность" required><textarea name="reason" placeholder="Причина запроса доступа" required></textarea><div class="actions"><button type="submit">Отправить заявку</button><a class="btn secondary" href="/staff-login">Вход сотрудников</a><a class="btn secondary" href="/">На главную</a></div></form></div></body></html>
    """, error=error, success=success)


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
                return redirect(url_for("staff_dashboard"))
            error = "Неверный Discord ID или пароль."
    return render_template_string("""
    <!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Вход сотрудников</title>
    <style>
        body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(135deg,#08111f,#0f172a,#111827);color:#e5e7eb;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}.card{width:100%;max-width:560px;background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98));border:1px solid rgba(148,163,184,.08);border-radius:24px;padding:26px}.error{margin-bottom:12px;padding:12px;border-radius:12px;background:rgba(220,38,38,.16);color:#fecaca}
        input{width:100%;padding:12px;border-radius:12px;border:1px solid #475569;background:#0f172a;color:white;margin-bottom:12px;box-sizing:border-box}.actions{display:flex;gap:10px;flex-wrap:wrap}
        button,a.btn{display:inline-block;padding:12px 16px;border:none;border-radius:12px;background:#2563eb;color:white;text-decoration:none;font-weight:bold;cursor:pointer} a.secondary{background:#334155}
    </style></head><body><div class="card"><h1>👥 Вход сотрудников</h1><p style="color:#94a3b8;line-height:1.6">Используйте Discord ID и пароль, отправленный после одобрения заявки.</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="post"><input type="text" name="discord_id" placeholder="Discord ID" required><input type="password" name="password" placeholder="Пароль" required><div class="actions"><button type="submit">Войти</button><a class="btn secondary" href="/request-access">Запросить доступ</a><a class="btn secondary" href="/">На главную</a></div></form></div></body></html>
    """, error=error)


@app.route("/staff/logout")
def staff_logout():
    session.pop("staff_auth", None)
    session.pop("staff_user", None)
    return redirect(url_for("staff_login"))


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
        <div class="card"><div>Подразделение</div><div class="stat-number" style="font-size:24px;">{user.get('department','—')}</div></div>
        <div class="card"><div>Discord ID</div><div class="stat-number" style="font-size:20px;">{user.get('discord_id','—')}</div></div>
    </div>
    <div class="row-2">
      <div class="card"><h3>👤 Ваш профиль</h3><div class="kv"><div class="box"><b>ФИО:</b><br>{user.get('fio','—')}</div><div class="box"><b>Подразделение:</b><br>{user.get('department','—')}</div><div class="box"><b>Discord ID:</b><br>{user.get('discord_id','—')}</div><div class="box"><b>Роль:</b><br>{user.get('role','employee')}</div></div></div>
      <div class="card"><h3>⚡ Быстрые действия</h3><div class="mini-list"><a class="btn" href="/staff/upload">⬆️ Загрузить документ</a><a class="btn secondary" href="/staff/documents">📂 Мои документы</a><a class="btn secondary" href="/staff/leadership">📨 Написать руководству</a><a class="btn secondary" href="/staff/change-password">🔐 Сменить пароль</a></div></div>
    </div>
    """
    return render_staff_page("Главная", content, active="dashboard")


@app.route("/staff/documents")
@staff_login_required
def staff_documents():
    user = session.get("staff_user", {})
    docs = staff_get_documents(user.get("discord_id"))
    rows = ""
    for item in docs:
        rows += f"<tr><td>{item.get('original_filename','')}</td><td>{item.get('file_ext','')}</td><td>{item.get('description') or '—'}</td><td>{item.get('created_at','')}</td><td><a href='/staff/download/{item.get('stored_filename')}'>Скачать</a></td></tr>"
    content = f"<div class='card'><h3>📂 Мои документы</h3><table><tr><th>Файл</th><th>Тип</th><th>Описание</th><th>Дата</th><th>Действие</th></tr>{rows or '<tr><td colspan="5">Документы ещё не загружались</td></tr>'}</table></div>"
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
                ext = original_name.rsplit('.',1)[1].lower() if '.' in original_name else ''
                staff_add_document(user.get("discord_id"), original_name, stored_name, ext, description)
                success = "Документ загружен."
    content = f"""
    <div class='card'>
      <h3>⬆️ Загрузка документа</h3>
      {f'<div class="message">{success}</div>' if success else ''}
      {f'<div class="message" style="background:rgba(220,38,38,.16);border-color:rgba(248,113,113,.18);">{error}</div>' if error else ''}
      <form method='post' enctype='multipart/form-data'>
        <input type='file' name='file' accept='.doc,.docx,.pdf,.png' required>
        <textarea name='description' placeholder='Краткое описание документа'></textarea>
        <button class='btn' type='submit'>Загрузить</button>
      </form>
      <div class='box'><b>Разрешены файлы:</b> .doc, .docx, .pdf, .png<br><b>Максимальный размер:</b> {MAX_UPLOAD_MB} МБ</div>
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
                staff_add_leadership_message(user.get("discord_id"), user.get("fio"), subject, message_text, original_name, stored_name)
                success = "Сообщение отправлено руководству."
    msgs = staff_get_messages(user.get("discord_id"))
    rows = ""
    for item in msgs[:20]:
        attachment = "—"
        if item.get("attachment_stored_filename"):
            attachment = f"<a href='/staff/download/{item.get('attachment_stored_filename')}'>{item.get('attachment_filename')}</a>"
        rows += f"<tr><td>{item.get('subject','')}</td><td>{item.get('status','')}</td><td>{item.get('created_at','')}</td><td>{attachment}</td></tr>"
    content = f"""
    <div class='row-2'>
      <div class='card'>
        <h3>📨 Новое сообщение руководству</h3>
        {f'<div class="message">{success}</div>' if success else ''}
        {f'<div class="message" style="background:rgba(220,38,38,.16);border-color:rgba(248,113,113,.18);">{error}</div>' if error else ''}
        <form method='post' enctype='multipart/form-data'>
          <input type='text' name='subject' placeholder='Тема обращения' required>
          <textarea name='message' placeholder='Текст обращения' required></textarea>
          <input type='file' name='file' accept='.doc,.docx,.pdf,.png'>
          <button class='btn' type='submit'>Отправить</button>
        </form>
      </div>
      <div class='card'><h3>ℹ️ Памятка</h3><div class='box'>Здесь можно направить служебное сообщение напрямую руководству и приложить файл.</div></div>
    </div>
    <div class='card'><h3>📋 Мои обращения руководству</h3><table><tr><th>Тема</th><th>Статус</th><th>Дата</th><th>Вложение</th></tr>{rows or '<tr><td colspan="4">Обращений пока нет</td></tr>'}</table></div>
    """
    return render_staff_page("Сообщение руководству", content, active="leadership")


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
            refreshed = get_web_user_by_discord_id(user.get("discord_id"))
            if refreshed:
                session["staff_user"] = refreshed
            success = "Пароль обновлён."
    content = f"""
    <div class='card'>
      <h3>🔐 Смена пароля</h3>
      {f'<div class="message">{success}</div>' if success else ''}
      {f'<div class="message" style="background:rgba(220,38,38,.16);border-color:rgba(248,113,113,.18);">{error}</div>' if error else ''}
      <form method='post'>
        <input type='password' name='old_password' placeholder='Старый пароль' required>
        <input type='password' name='new_password' placeholder='Новый пароль' required>
        <input type='password' name='confirm_password' placeholder='Подтвердите новый пароль' required>
        <button class='btn' type='submit'>Сохранить новый пароль</button>
      </form>
    </div>
    """
    return render_staff_page("Смена пароля", content, active="password")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password == WEB_PANEL_PASSWORD:
            session["panel_auth"] = True
            return redirect(url_for("dashboard"))
        error = "Неверный пароль."
    return render_template_string("""
    <!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Вход в панель</title>
    <style>body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(135deg,#08111f,#0f172a,#111827);color:#e5e7eb;min-height:100vh}.login-wrap{display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}.login-card{width:100%;max-width:420px;background:linear-gradient(180deg,rgba(24,34,53,.98),rgba(19,28,44,.98));border:1px solid rgba(148,163,184,.08);border-radius:24px;padding:26px}.error{margin-top:12px;padding:12px;border-radius:12px;background:rgba(220,38,38,.16);color:#fecaca}input{width:100%;padding:12px;border-radius:12px;border:1px solid #475569;background:#0f172a;color:white;margin-bottom:14px;box-sizing:border-box}button{width:100%;padding:12px;border:none;border-radius:12px;background:#2563eb;color:white;font-weight:bold;cursor:pointer}.back{display:inline-block;margin-top:16px;color:#94a3b8;text-decoration:none}</style></head>
    <body><div class="login-wrap"><div class="login-card"><h1>🔐 Вход в веб-панель</h1><p style="color:#94a3b8">Панель управления СУ СК</p><form method="post"><input type="password" name="password" placeholder="Введите пароль" required><button type="submit">Войти</button></form>{% if error %}<div class="error">{{ error }}</div>{% endif %}<a class="back" href="/">← Вернуться на главную</a></div></div></body></html>
    """, error=error)


@app.route("/logout")
def logout():
    session.pop("panel_auth", None)
    return redirect(url_for("login"))


@app.route("/admin/download/<filename>")
@login_required
def admin_download(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.route("/backup", methods=["POST"])
@login_required
def make_backup():
    backup_path = backup_database()
    return redirect(url_for("dashboard", message=f"Бэкап создан: {backup_path}"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.run(host="0.0.0.0", port=port)
