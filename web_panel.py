import os
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
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
    get_recent_hr,
    get_all_employees,
    search_employee_by_discord_id,
    upsert_employee_from_web,
    backup_database,
    get_appeal_by_number,
    get_connection,
)

app = Flask(__name__)
app.secret_key = os.getenv("WEB_PANEL_SECRET", "sk_panel_secret_key_change_me")
WEB_PANEL_PASSWORD = os.getenv("WEB_PANEL_PASSWORD", "12345")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

init_db()


# =========================
# AUTH
# =========================

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("panel_auth"):
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


# =========================
# HELPERS
# =========================

def load_discipline_records(limit: int = 200):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM discipline_records
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(x) for x in rows]


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
    values = [
        stats["new_count"],
        stats["work_count"],
        stats["clarify_count"],
        stats["closed_count"],
        stats["rejected_count"],
    ]

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


def get_appeal_history_for_page(number: str):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM appeal_history
            WHERE appeal_number = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (number,),
        ).fetchall()
        return [dict(x) for x in rows]


def add_web_history(appeal_number: str, action: str, details: str):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO appeal_history (
                appeal_number, action, actor_id, actor_name, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (appeal_number, action, 0, "WEB_PANEL", details),
        )
        conn.commit()


def update_appeal_from_web(number: str, form: dict):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE appeals
            SET
                status = ?,
                department = ?,
                priority = ?,
                assigned_to = ?,
                clarification_text = ?,
                resolution_text = ?,
                updated_at = ?
            WHERE number = ?
            """,
            (
                form.get("status", "").strip(),
                form.get("department", "").strip(),
                form.get("priority", "").strip(),
                int(form["assigned_to"]) if form.get("assigned_to", "").strip().isdigit() else None,
                form.get("clarification_text", "").strip() or None,
                form.get("resolution_text", "").strip() or None,
                __import__("datetime").datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                number,
            ),
        )
        conn.commit()

    add_web_history(
        number,
        "Изменение через WEB_PANEL",
        (
            f"Статус={form.get('status','')} | "
            f"Подразделение={form.get('department','')} | "
            f"Приоритет={form.get('priority','')} | "
            f"Исполнитель={form.get('assigned_to','') or '—'}"
        ),
    )


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

    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>{{ title }}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            :root {
                --bg1:#08111f;
                --bg2:#0f172a;
                --bg3:#111827;
                --card:#182235;
                --card2:#1f2d44;
                --line:#334155;
                --text:#e5e7eb;
                --muted:#94a3b8;
                --blue:#2563eb;
                --blue2:#1d4ed8;
                --green:#16a34a;
                --red:#dc2626;
                --yellow:#ca8a04;
                --purple:#7c3aed;
                --shadow:0 16px 35px rgba(0,0,0,.30);
                --radius:20px;
            }

            * { box-sizing:border-box; }

            body {
                margin:0;
                padding:0;
                font-family:Arial, sans-serif;
                color:var(--text);
                background:
                    radial-gradient(circle at top right, rgba(37,99,235,0.12), transparent 20%),
                    radial-gradient(circle at top left, rgba(124,58,237,0.10), transparent 18%),
                    linear-gradient(135deg, var(--bg1), var(--bg2), var(--bg3));
                min-height:100vh;
            }

            .layout {
                display:grid;
                grid-template-columns: 280px 1fr;
                min-height:100vh;
            }

            .sidebar {
                background:rgba(10,16,30,0.88);
                backdrop-filter: blur(10px);
                border-right:1px solid rgba(148,163,184,.08);
                padding:24px 18px;
                position:sticky;
                top:0;
                height:100vh;
            }

            .brand {
                margin-bottom:26px;
            }

            .brand h1 {
                margin:0 0 8px 0;
                font-size:22px;
            }

            .brand p {
                margin:0;
                color:var(--muted);
                font-size:14px;
                line-height:1.45;
            }

            .nav {
                display:grid;
                gap:10px;
            }

            .nav a {
                display:block;
                padding:14px 14px;
                border-radius:14px;
                color:#dbeafe;
                text-decoration:none;
                background:transparent;
                transition:.15s ease;
                border:1px solid transparent;
            }

            .nav a:hover {
                background:rgba(37,99,235,.12);
                border-color:rgba(96,165,250,.18);
                text-decoration:none;
            }

            .nav a.active {
                background:linear-gradient(135deg, rgba(37,99,235,.22), rgba(124,58,237,.16));
                border-color:rgba(96,165,250,.22);
            }

            .side-bottom {
                margin-top:24px;
                padding-top:18px;
                border-top:1px solid rgba(148,163,184,.08);
                color:var(--muted);
                font-size:13px;
            }

            .main {
                padding:28px;
            }

            .topbar {
                display:flex;
                justify-content:space-between;
                align-items:center;
                gap:16px;
                margin-bottom:20px;
                flex-wrap:wrap;
            }

            .topbar h2 {
                margin:0;
                font-size:26px;
            }

            .top-actions {
                display:flex;
                gap:12px;
                flex-wrap:wrap;
            }

            .btn {
                display:inline-block;
                padding:11px 16px;
                border:none;
                border-radius:12px;
                background:var(--blue);
                color:white;
                font-weight:bold;
                cursor:pointer;
                text-decoration:none;
                box-shadow:var(--shadow);
            }

            .btn:hover {
                background:var(--blue2);
                text-decoration:none;
            }

            .btn.secondary {
                background:#334155;
            }

            .btn.secondary:hover {
                background:#475569;
            }

            .message {
                padding:14px 16px;
                border-radius:14px;
                background:rgba(37,99,235,0.18);
                border:1px solid rgba(147,197,253,0.20);
                margin-bottom:20px;
            }

            .muted {
                color:var(--muted);
            }

            .grid {
                display:grid;
                grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));
                gap:16px;
                margin-bottom:24px;
            }

            .card {
                background:linear-gradient(180deg, rgba(24,34,53,.98), rgba(19,28,44,.98));
                border:1px solid rgba(148,163,184,.08);
                border-radius:var(--radius);
                padding:18px;
                box-shadow:var(--shadow);
                margin-bottom:20px;
            }

            .row-2 {
                display:grid;
                grid-template-columns:1fr 1fr;
                gap:18px;
                margin-bottom:24px;
            }

            .row-3 {
                display:grid;
                grid-template-columns:1.2fr .8fr .8fr;
                gap:18px;
                margin-bottom:24px;
            }

            .stat-number {
                font-size:32px;
                font-weight:bold;
                margin-top:8px;
            }

            table {
                width:100%;
                border-collapse:collapse;
                background:transparent;
                border-radius:16px;
                overflow:hidden;
            }

            th, td {
                padding:12px;
                border-bottom:1px solid var(--line);
                text-align:left;
                vertical-align:top;
            }

            th {
                background:#0d1728;
                color:#cbd5e1;
            }

            tr:hover td {
                background:rgba(255,255,255,0.02);
            }

            input, select, textarea {
                width:100%;
                padding:11px 12px;
                border-radius:12px;
                border:1px solid #475569;
                background:#0f172a;
                color:white;
                margin-bottom:12px;
                outline:none;
            }

            textarea {
                min-height:100px;
                resize:vertical;
            }

            .toolbar {
                display:flex;
                gap:12px;
                flex-wrap:wrap;
                margin-bottom:12px;
            }

            .toolbar form {
                display:flex;
                gap:10px;
                flex-wrap:wrap;
                width:100%;
            }

            .toolbar input, .toolbar select {
                margin-bottom:0;
                min-width:170px;
                flex:1;
            }

            .mini-list {
                display:grid;
                gap:10px;
            }

            .mini-item {
                padding:12px;
                border-radius:14px;
                background:rgba(255,255,255,0.03);
                border:1px solid rgba(148,163,184,.08);
            }

            .big-center {
                font-size:18px;
                font-weight:bold;
                margin-bottom:6px;
            }

            .small {
                font-size:13px;
                color:var(--muted);
            }

            .chart {
                display:grid;
                gap:10px;
                margin-top:10px;
            }

            .bar-row {
                display:grid;
                grid-template-columns:160px 1fr 40px;
                gap:10px;
                align-items:center;
            }

            .bar {
                height:12px;
                border-radius:999px;
                background:#0f172a;
                overflow:hidden;
            }

            .bar > span {
                display:block;
                height:100%;
                border-radius:999px;
                background:linear-gradient(90deg, #2563eb, #60a5fa);
            }

            .page-content img {
                max-width:100%;
                border-radius:14px;
                border:1px solid rgba(148,163,184,.08);
            }

            .kv {
                display:grid;
                grid-template-columns:1fr 1fr;
                gap:14px;
                margin-bottom:14px;
            }

            .box {
                background:#0f172a;
                border:1px solid rgba(148,163,184,.08);
                border-radius:14px;
                padding:14px;
            }

            .timeline {
                display:grid;
                gap:12px;
            }

            .timeline-item {
                padding:12px;
                border-radius:14px;
                background:rgba(255,255,255,0.03);
                border:1px solid rgba(148,163,184,.08);
            }

            @media (max-width: 1100px) {
                .layout { grid-template-columns:1fr; }
                .sidebar {
                    position:static;
                    height:auto;
                    border-right:none;
                    border-bottom:1px solid rgba(148,163,184,.08);
                }
                .row-2, .row-3, .kv { grid-template-columns:1fr; }
            }
        </style>
        <script>
            setTimeout(function() {
                const auto = {{ "true" if active in ["dashboard", "analytics"] else "false" }};
                if (auto) window.location.reload();
            }, 30000);
        </script>
    </head>
    <body>
        <div class="layout">
            <aside class="sidebar">
                <div class="brand">
                    <h1>👑 СУ СК</h1>
                    <p>Внутренняя панель управления<br>Следственным управлением</p>
                </div>

                <nav class="nav">
                    <a href="/" class="{{ 'active' if active == 'dashboard' else '' }}">📊 Дашборд</a>
                    <a href="/appeals" class="{{ 'active' if active == 'appeals' else '' }}">📨 Обращения</a>
                    <a href="/employees" class="{{ 'active' if active == 'employees' else '' }}">👥 Кадры</a>
                    <a href="/analytics" class="{{ 'active' if active == 'analytics' else '' }}">📈 Аналитика</a>
                    <a href="/discipline" class="{{ 'active' if active == 'discipline' else '' }}">⚖️ Дисциплина</a>
                    <a href="/logout">🚪 Выход</a>
                </nav>

                <div class="side-bottom">
                    Автообновление: каждые 30 сек на дашборде и аналитике
                </div>
            </aside>

            <main class="main">
                <div class="topbar">
                    <div>
                        <h2>{{ title }}</h2>
                    </div>
                    <div class="top-actions">
                        <form method="post" action="/backup" style="margin:0;">
                            <button class="btn" type="submit">💾 Бэкап базы</button>
                        </form>
                        <a class="btn secondary" href="/">↻ Обновить</a>
                    </div>
                </div>

                {% if message %}
                    <div class="message">{{ message }}</div>
                {% endif %}

                <div class="page-content">
                    {{ content|safe }}
                </div>
            </main>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, title=title, content=content, active=active, message=message)


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        if password == WEB_PANEL_PASSWORD:
            session["panel_auth"] = True
            return redirect(url_for("dashboard"))
        error = "Неверный пароль."

    template = """
    <!doctype html>
    <html lang="ru">
    <head>
        <meta charset="utf-8">
        <title>Вход в панель</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                margin:0;
                font-family:Arial,sans-serif;
                background:
                    radial-gradient(circle at top right, rgba(37,99,235,0.12), transparent 20%),
                    radial-gradient(circle at top left, rgba(124,58,237,0.10), transparent 18%),
                    linear-gradient(135deg, #08111f, #0f172a, #111827);
                color:#e5e7eb;
                min-height:100vh;
            }
            .login-wrap {
                display:flex;
                min-height:100vh;
                align-items:center;
                justify-content:center;
                padding:24px;
            }
            .login-card {
                width:100%;
                max-width:420px;
                background:linear-gradient(180deg, rgba(24,34,53,.98), rgba(19,28,44,.98));
                border:1px solid rgba(148,163,184,.08);
                border-radius:24px;
                padding:26px;
                box-shadow:0 16px 35px rgba(0,0,0,.30);
            }
            h1 { margin:0 0 10px 0; }
            p { color:#94a3b8; margin-bottom:18px; }
            input {
                width:100%;
                padding:12px;
                border-radius:12px;
                border:1px solid #475569;
                background:#0f172a;
                color:white;
                margin-bottom:14px;
                box-sizing:border-box;
            }
            button {
                width:100%;
                padding:12px;
                border:none;
                border-radius:12px;
                background:#2563eb;
                color:white;
                font-weight:bold;
                cursor:pointer;
            }
            .error {
                margin-top:12px;
                padding:12px;
                border-radius:12px;
                background:rgba(220,38,38,.16);
                color:#fecaca;
            }
        </style>
    </head>
    <body>
        <div class="login-wrap">
            <div class="login-card">
                <h1>🔐 Вход в веб-панель</h1>
                <p>Панель управления СУ СК</p>

                <form method="post">
                    <input type="password" name="password" placeholder="Введите пароль" required>
                    <button type="submit">Войти</button>
                </form>

                {% if error %}
                    <div class="error">{{ error }}</div>
                {% endif %}
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(template, error=error)


@app.route("/logout")
def logout():
    session.pop("panel_auth", None)
    return redirect(url_for("login"))


# =========================
# DASHBOARD
# =========================

@app.route("/")
@login_required
def dashboard():
    employees = get_all_employees()
    stats = get_stats()
    dep_stats = get_department_stats(employees)
    top = get_top_employees(employees, 5)

    values = [
        stats["new_count"],
        stats["work_count"],
        stats["clarify_count"],
        stats["closed_count"],
        stats["rejected_count"],
    ]
    max_value = max(values) if max(values) > 0 else 1

    analytics = [
        ("Новые", stats["new_count"], round(stats["new_count"] / max_value * 100)),
        ("В работе", stats["work_count"], round(stats["work_count"] / max_value * 100)),
        ("На уточнении", stats["clarify_count"], round(stats["clarify_count"] / max_value * 100)),
        ("Закрытые", stats["closed_count"], round(stats["closed_count"] / max_value * 100)),
        ("Отказы", stats["rejected_count"], round(stats["rejected_count"] / max_value * 100)),
    ]

    top_html = ""
    for idx, emp in enumerate(top, start=1):
        top_html += f"""
        <div class="mini-item">
            <div class="big-center">#{idx} {emp.get("fio", "—")}</div>
            <div class="small">Закрыто дел: {emp.get("closed_cases_count", 0)} | Всего дел: {emp.get("cases_count", 0)}</div>
        </div>
        """

    content = f"""
    <div class="grid">
        <div class="card"><div>Новые обращения</div><div class="stat-number">{stats["new_count"]}</div></div>
        <div class="card"><div>В работе</div><div class="stat-number">{stats["work_count"]}</div></div>
        <div class="card"><div>На уточнении</div><div class="stat-number">{stats["clarify_count"]}</div></div>
        <div class="card"><div>Закрытые</div><div class="stat-number">{stats["closed_count"]}</div></div>
        <div class="card"><div>Анкет на рассмотрении</div><div class="stat-number">{stats["hr_count"]}</div></div>
        <div class="card"><div>Истекших испытательных</div><div class="stat-number">{stats["probation_count"]}</div></div>
    </div>

    <div class="row-3">
        <div class="card">
            <h3>📊 Быстрая аналитика</h3>
            <div class="chart">
                {''.join([
                    f'''
                    <div class="bar-row">
                        <div>{label}</div>
                        <div class="bar"><span style="width:{width}%"></span></div>
                        <div>{value}</div>
                    </div>
                    '''
                    for label, value, width in analytics
                ])}
            </div>
        </div>

        <div class="card">
            <h3>🏢 Подразделения</h3>
            <div class="mini-list">
                <div class="mini-item">
                    <div class="big-center">СО</div>
                    <div class="small">Сотрудников: {dep_stats["so_count"]}</div>
                </div>
                <div class="mini-item">
                    <div class="big-center">ВСО</div>
                    <div class="small">Сотрудников: {dep_stats["vso_count"]}</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>🏆 Топ сотрудников</h3>
            <div class="mini-list">
                {top_html or '<div class="mini-item">Нет данных</div>'}
            </div>
        </div>
    </div>
    """

    return render_page("Дашборд", content, active="dashboard")


# =========================
# APPEALS
# =========================

@app.route("/appeals")
@login_required
def appeals():
    all_appeals = get_recent_appeals(200)

    appeal_status = request.args.get("appeal_status", "").strip()
    appeal_department = request.args.get("appeal_department", "").strip()
    appeal_number = request.args.get("appeal_number", "").strip()
    appeal_priority = request.args.get("appeal_priority", "").strip()

    appeals_filtered = filter_appeals(
        all_appeals,
        appeal_status=appeal_status,
        appeal_department=appeal_department,
        appeal_number=appeal_number,
        appeal_priority=appeal_priority,
    )

    rows = ""
    for item in appeals_filtered[:100]:
        rows += f"""
        <tr>
            <td>{item.get("number", "")}</td>
            <td>{item.get("status", "")}</td>
            <td>{item.get("department", "")}</td>
            <td>{item.get("priority", "")}</td>
            <td>{item.get("created_at", "")}</td>
            <td><a href="/appeal/{item.get("number", "")}">Карточка</a></td>
            <td><a href="/appeal/{item.get("number", "")}/edit">Редактировать</a></td>
        </tr>
        """

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
            <tr>
                <th>Номер</th>
                <th>Статус</th>
                <th>Подразделение</th>
                <th>Приоритет</th>
                <th>Создано</th>
                <th>Открыть</th>
                <th>Ред.</th>
            </tr>
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
    history_html = ""
    for row in history:
        history_html += f"""
        <div class="timeline-item">
            <b>{row.get("action", "—")}</b><br>
            <span class="small">{row.get("created_at", "—")} | {row.get("actor_name") or "Неизвестно"}</span><br><br>
            {row.get("details") or "—"}
        </div>
        """

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

        <div class="box" style="margin-bottom:14px;">
            <b>Описание:</b><br><br>
            {appeal.get("description") or "—"}
        </div>

        <div class="box" style="margin-bottom:14px;">
            <b>Уточнение:</b><br><br>
            {appeal.get("clarification_text") or "—"}
        </div>

        <div class="box" style="margin-bottom:14px;">
            <b>Ответ заявителя:</b><br><br>
            {appeal.get("citizen_reply_text") or "—"}
        </div>

        <div class="box" style="margin-bottom:14px;">
            <b>Итог / причина:</b><br><br>
            {appeal.get("resolution_text") or "—"}
        </div>
    </div>

    <div class="card">
        <h3>🕒 История обращения</h3>
        <div class="timeline">
            {history_html or '<div class="timeline-item">История пуста</div>'}
        </div>
    </div>
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
        return redirect(url_for("appeal_card", number=number, message="Обращение обновлено"))

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

            <select name="assigned_to">
                {options}
            </select>

            <textarea name="clarification_text" placeholder="Текст уточнения">{appeal.get("clarification_text") or ""}</textarea>
            <textarea name="resolution_text" placeholder="Итог / причина">{appeal.get("resolution_text") or ""}</textarea>

            <button class="btn" type="submit">Сохранить изменения</button>
        </form>
    </div>
    """
    return render_page(f"Редактирование {number}", content, active="appeals")


# =========================
# EMPLOYEES
# =========================

@app.route("/employees")
@login_required
def employees():
    all_employees = get_all_employees()

    search_value = request.args.get("search_discord_id", "").strip()
    employee_department = request.args.get("employee_department", "").strip()
    employee_fio = request.args.get("employee_fio", "").strip()
    employee_status = request.args.get("employee_status", "").strip()

    searched_employee = None
    if search_value.isdigit():
        searched_employee = search_employee_by_discord_id(int(search_value))

    employees_filtered = filter_employees(
        all_employees,
        department=employee_department,
        fio=employee_fio,
        status=employee_status,
    )

    rows = ""
    for item in employees_filtered[:150]:
        rows += f"""
        <tr>
            <td>{item.get("fio", "")}</td>
            <td>{item.get("discord_id", "")}</td>
            <td>{item.get("department", "")}</td>
            <td>{item.get("position", "")}</td>
            <td>{item.get("rank_name", "")}</td>
            <td>{item.get("status", "")}</td>
            <td>{item.get("cases_count", 0)}</td>
            <td>{item.get("closed_cases_count", 0)}</td>
            <td><a href="/employee/{item.get("discord_id", 0)}">Карточка</a></td>
            <td><a href="/employee/{item.get("discord_id", 0)}/edit">Ред.</a></td>
        </tr>
        """

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

                <select name="department" required>
                    <option value="СО">СО</option>
                    <option value="ВСО">ВСО</option>
                </select>

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
            <tr>
                <th>ФИО</th>
                <th>Discord ID</th>
                <th>Подразделение</th>
                <th>Должность</th>
                <th>Звание</th>
                <th>Статус</th>
                <th>Дел</th>
                <th>Закрыто</th>
                <th>Открыть</th>
                <th>Ред.</th>
            </tr>
            {rows or '<tr><td colspan="10">Нет данных</td></tr>'}
        </table>
    </div>
    """

    return render_page("Кадры", content, active="employees")


@app.route("/employee/<int:discord_id>")
@login_required
def employee_card(discord_id):
    employee = get_employee_by_id_for_page(discord_id)
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

        <div class="box">
            <b>Примечания:</b><br><br>
            {employee.get("notes") or "—"}
        </div>
    </div>
    """
    return render_page(f"Сотрудник {employee.get('fio', '')}", content, active="employees")


@app.route("/employee/<int:discord_id>/edit", methods=["GET", "POST"])
@login_required
def employee_edit(discord_id):
    employee = get_employee_by_id_for_page(discord_id)
    if not employee:
        return render_page("Сотрудник не найден", "<div class='card'>Сотрудник не найден.</div>", active="employees")

    if request.method == "POST":
        update_employee_from_web(discord_id, request.form)
        return redirect(url_for("employee_card", discord_id=discord_id, message="Карточка сотрудника обновлена"))

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
    fio = request.form["fio"].strip()
    department = request.form["department"].strip()
    position = request.form["position"].strip()
    rank_name = request.form["rank_name"].strip()
    status = request.form["status"].strip()
    notes = request.form.get("notes", "").strip()

    upsert_employee_from_web(
        discord_id=discord_id,
        fio=fio,
        department=department,
        position=position,
        rank_name=rank_name,
        status=status,
        notes=notes,
    )

    return redirect(url_for("employees", message="Карточка сотрудника сохранена"))


# =========================
# ANALYTICS
# =========================

@app.route("/analytics")
@login_required
def analytics():
    employees = get_all_employees()
    status_chart = save_status_chart()
    employee_chart = save_employee_chart(employees)
    department_chart = save_department_chart(employees)

    content = f"""
    <div class="row-2">
        <div class="card">
            <h3>📊 Статусы обращений</h3>
            <img src="/static/{status_chart}" alt="Статусы обращений">
        </div>

        <div class="card">
            <h3>🏆 Топ сотрудников</h3>
            <img src="/static/{employee_chart}" alt="Топ сотрудников">
        </div>
    </div>

    <div class="card">
        <h3>🏢 Подразделения</h3>
        <img src="/static/{department_chart}" alt="Подразделения">
    </div>
    """
    return render_page("Аналитика", content, active="analytics")


# =========================
# DISCIPLINE
# =========================

@app.route("/discipline")
@login_required
def discipline():
    fio = request.args.get("fio", "").strip()
    action_type = request.args.get("action_type", "").strip()

    records = filter_discipline(load_discipline_records(200), fio=fio, action_type=action_type)

    rows = ""
    for item in records:
        rows += f"""
        <tr>
            <td>{item.get("number", "")}</td>
            <td>{item.get("fio", "")}</td>
            <td>{item.get("action_type", "")}</td>
            <td>{item.get("reason", "")}</td>
            <td>{item.get("issued_by_name", "")}</td>
            <td>{item.get("created_at", "")}</td>
        </tr>
        """

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
            <tr>
                <th>Номер</th>
                <th>Сотрудник</th>
                <th>Тип</th>
                <th>Причина</th>
                <th>Кто выдал</th>
                <th>Дата</th>
            </tr>
            {rows or '<tr><td colspan="6">Нет записей</td></tr>'}
        </table>
    </div>
    """
    return render_page("Дисциплина", content, active="discipline")


# =========================
# BACKUP
# =========================

@app.route("/backup", methods=["POST"])
@login_required
def make_backup():
    backup_path = backup_database()
    return redirect(url_for("dashboard", message=f"Бэкап создан: {backup_path}"))


# =========================
# RUN
# =========================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)