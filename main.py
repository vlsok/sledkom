import logging
import re
import sys
import traceback
from datetime import datetime

import disnake
from disnake.ext import commands, tasks

from config import (
    TOKEN,
    GUILD_ID,
    APPEALS_LOG_CHANNEL_ID,
    HR_LOG_CHANNEL_ID,
    SYSTEM_LOG_CHANNEL_ID,
    SO_CATEGORY_ID,
    VSO_CATEGORY_ID,
    ARCHIVE_CATEGORY_ID,
    REMINDER_HOURS,
    PROBATION_DAYS,
    ROLE_LEADER,
    ROLE_DEPUTY,
    ROLE_SO_HEAD,
    ROLE_VSO_HEAD,
    ROLE_SO,
    ROLE_VSO,
    ROLE_INVESTIGATOR,
    ROLE_CRIMINALIST,
    ROLE_TRAINEE,
    EMPLOYEE_ROLE_ID,
    LEADERSHIP_ROLE_IDS,
    STAFF_ROLE_IDS,
    SO_ROLE_IDS,
    VSO_ROLE_IDS,
    RANK_ROLE_IDS,
    LEADER_PANEL_ROLE_IDS,
)

from database import (
    init_db,
    create_appeal,
    get_appeal_by_number,
    get_appeal_history,
    get_active_appeals,
    count_appeals_by_status,
    count_hr_by_status,
    set_appeal_log_message_id,
    set_appeal_work_channel,
    set_appeal_assigned_to,
    set_appeal_clarification,
    set_citizen_reply,
    close_appeal,
    archive_appeal,
    add_appeal_history,
    get_connection,
    create_hr_request,
    get_hr_request_by_number,
    set_hr_log_message_id,
    update_hr_status,
    create_employee,
    get_employee_by_discord_id,
    update_employee_status,
    extend_probation,
    update_employee_rank,
    add_discipline_record,
    get_due_probations,
    backup_database,
)

# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("sk_bot")


def log_exception(context: str, exc: Exception):
    logger.error("Ошибка в %s: %s", context, exc)
    traceback.print_exc()


# =========================
# BOT
# =========================

intents = disnake.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.InteractionBot(intents=intents)

AUTHOR_NAME = "Следственный комитет РФ | СУ по Ленинградской области"
FOOTER_TEXT = "СУ СК РФ • Зареченск"

STATUS_LABELS = {
    "Принято": "🟡 Принято",
    "В работе": "🟠 В работе",
    "Требует уточнения": "🟣 Требует уточнения",
    "Закрыто": "🟢 Закрыто",
    "Отказано": "🔴 Отказано",
    "Архив": "⚫ Архив",
}

PRIORITY_LABELS = {
    "Высокий": "🔴 Высокий",
    "Обычный": "🟡 Обычный",
    "Низкий": "⚪ Низкий",
}

RANK_OPTIONS = [
    "Младший лейтенант юстиции",
    "Лейтенант юстиции",
    "Старший лейтенант юстиции",
    "Капитан юстиции",
    "Майор юстиции",
    "Подполковник юстиции",
    "Полковник юстиции",
    "Генерал-майор юстиции",
]


# =========================
# HELPERS
# =========================

def style_embed(embed: disnake.Embed) -> disnake.Embed:
    embed.set_author(name=AUTHOR_NAME)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def section(title: str) -> str:
    return f"**{title}**"


def has_any_role(member: disnake.Member, role_ids: set[int]) -> bool:
    return any(role.id in role_ids for role in member.roles)


def member_has_staff_access(member: disnake.Member) -> bool:
    return has_any_role(member, STAFF_ROLE_IDS)


def member_has_hr_access(member: disnake.Member) -> bool:
    return has_any_role(member, LEADERSHIP_ROLE_IDS)


def member_has_leader_panel_access(member: disnake.Member) -> bool:
    return has_any_role(member, LEADER_PANEL_ROLE_IDS)


def get_member_role_names(member: disnake.Member) -> list[str]:
    return [role.name for role in member.roles]


def get_staff_match_info(member: disnake.Member) -> tuple[bool, list[str]]:
    matched = []
    for role in member.roles:
        if role.id in STAFF_ROLE_IDS:
            matched.append(f"{role.name} ({role.id})")
    return len(matched) > 0, matched


def sanitize_channel_name(text: str) -> str:
    text = text.lower().replace(" ", "-")
    text = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:70] if text else "appeal"


def startup_debug(guild: disnake.Guild):
    logger.info("========== STARTUP DEBUG ==========")

    required_channels = {
        "APPEALS_LOG_CHANNEL_ID": APPEALS_LOG_CHANNEL_ID,
        "HR_LOG_CHANNEL_ID": HR_LOG_CHANNEL_ID,
        "SYSTEM_LOG_CHANNEL_ID": SYSTEM_LOG_CHANNEL_ID,
    }

    required_categories = {
        "SO_CATEGORY_ID": SO_CATEGORY_ID,
        "VSO_CATEGORY_ID": VSO_CATEGORY_ID,
        "ARCHIVE_CATEGORY_ID": ARCHIVE_CATEGORY_ID,
    }

    required_roles = {
        "ROLE_LEADER": ROLE_LEADER,
        "ROLE_DEPUTY": ROLE_DEPUTY,
        "ROLE_SO_HEAD": ROLE_SO_HEAD,
        "ROLE_VSO_HEAD": ROLE_VSO_HEAD,
        "ROLE_SO": ROLE_SO,
        "ROLE_VSO": ROLE_VSO,
        "ROLE_INVESTIGATOR": ROLE_INVESTIGATOR,
        "ROLE_CRIMINALIST": ROLE_CRIMINALIST,
        "ROLE_TRAINEE": ROLE_TRAINEE,
        "EMPLOYEE_ROLE_ID": EMPLOYEE_ROLE_ID,
    }

    for name, channel_id in required_channels.items():
        channel = guild.get_channel(channel_id)
        if channel:
            logger.info("[OK] %s -> %s (%s)", name, channel.name, channel.id)
        else:
            logger.error("[MISSING] %s -> %s", name, channel_id)

    for name, category_id in required_categories.items():
        category = guild.get_channel(category_id)
        if category:
            logger.info("[OK] %s -> %s (%s)", name, category.name, category.id)
        else:
            logger.error("[MISSING] %s -> %s", name, category_id)

    for name, role_id in required_roles.items():
        role = guild.get_role(role_id)
        if role:
            logger.info("[OK] %s -> %s (%s)", name, role.name, role.id)
        else:
            logger.error("[MISSING] %s -> %s", name, role_id)

    logger.info("========== END STARTUP DEBUG ==========")


async def send_system_log(
    guild: disnake.Guild,
    title: str,
    description: str,
    color: disnake.Color = disnake.Color.dark_blue(),
    view: disnake.ui.View | None = None,
):
    try:
        channel = guild.get_channel(SYSTEM_LOG_CHANNEL_ID)
        if channel:
            embed = style_embed(disnake.Embed(title=title, description=description, color=color))
            await channel.send(embed=embed, view=view)
    except Exception as e:
        log_exception("send_system_log", e)


async def send_clarification_dm(appeal: dict, clarification_text: str):
    try:
        user = await bot.fetch_user(appeal["user_id"])
    except Exception as e:
        log_exception("fetch_user clarification", e)
        return

    responsible_text = "Не назначен"
    if appeal.get("assigned_to"):
        responsible_text = f"<@{appeal['assigned_to']}> (`{appeal['assigned_to']}`)"
    elif appeal.get("accepted_by"):
        responsible_text = f"<@{appeal['accepted_by']}> (`{appeal['accepted_by']}`)"

    embed = disnake.Embed(
        title=f"📨 Уточнение по обращению № {appeal['number']}",
        description="По вашему обращению требуется дополнительная информация.",
        color=disnake.Color.purple(),
    )
    embed.add_field(name="📌 Статус", value="🟣 Требует уточнения", inline=True)
    embed.add_field(name="🏢 Подразделение", value=appeal.get("department") or "Не определено", inline=True)
    embed.add_field(name="📄 Тип обращения", value=appeal.get("appeal_type", "Не указано"), inline=True)
    embed.add_field(name="👤 Ответственный", value=responsible_text, inline=False)
    embed.add_field(name="📝 Что нужно уточнить", value=clarification_text[:1024], inline=False)
    embed.add_field(
        name="📞 Что делать дальше",
        value="Используйте команду `/reply_clarification`, чтобы отправить ответ по этому обращению.",
        inline=False,
    )
    embed.add_field(name="🆔 Номер обращения", value=appeal["number"], inline=False)
    style_embed(embed)

    try:
        await user.send(embed=embed)
    except Exception as e:
        log_exception("send clarification dm", e)


async def send_resolution_dm(appeal: dict, status: str, resolution_text: str):
    try:
        user = await bot.fetch_user(appeal["user_id"])
    except Exception as e:
        log_exception("fetch_user resolution", e)
        return

    color = disnake.Color.green() if status == "Закрыто" else disnake.Color.red()
    title = "✅ Обращение закрыто" if status == "Закрыто" else "❌ По обращению вынесен отказ"

    embed = disnake.Embed(
        title=f"{title} — № {appeal['number']}",
        description="Информируем вас о результате рассмотрения обращения.",
        color=color,
    )
    embed.add_field(name="📊 Статус", value=STATUS_LABELS.get(status, status), inline=True)
    embed.add_field(name="🏢 Подразделение", value=appeal.get("department") or "Не определено", inline=True)
    embed.add_field(name="📄 Тип обращения", value=appeal.get("appeal_type", "Не указано"), inline=True)
    embed.add_field(name="📝 Итог / причина", value=resolution_text[:1024], inline=False)
    style_embed(embed)

    try:
        await user.send(embed=embed)
    except Exception as e:
        log_exception("send resolution dm", e)


# =========================
# EMBEDS
# =========================

def build_panel_embed() -> disnake.Embed:
    embed = disnake.Embed(
        title="📄 Служебная панель СУ СК",
        description=(
            "Ниже доступны основные действия.\n\n"
            "📨 **Подать обращение** — заявление, жалоба, сообщение о преступлении, рапорт.\n"
            "📋 **Подать анкету** — анкета на трудоустройство.\n"
            "📩 **Ответить на уточнение** — команда `/reply_clarification`."
        ),
        color=disnake.Color.blue(),
    )
    return style_embed(embed)


def build_appeal_embed(appeal: dict, author_mention: str) -> disnake.Embed:
    status = appeal.get("status", "Неизвестно")
    label = STATUS_LABELS.get(status, status)
    priority = PRIORITY_LABELS.get(appeal.get("priority", "Обычный"), appeal.get("priority", "Обычный"))

    color = disnake.Color.blue()
    if status == "В работе":
        color = disnake.Color.orange()
    elif status == "Требует уточнения":
        color = disnake.Color.purple()
    elif status == "Закрыто":
        color = disnake.Color.green()
    elif status == "Отказано":
        color = disnake.Color.red()
    elif status == "Архив":
        color = disnake.Color.dark_grey()

    embed = disnake.Embed(title=f"📨 Обращение № {appeal['number']}", color=color)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📌 Основная информация"), inline=False)
    embed.add_field(name="📄 Тип", value=appeal["appeal_type"], inline=True)
    embed.add_field(name="📊 Статус", value=label, inline=True)
    embed.add_field(name="⚠️ Приоритет", value=priority, inline=True)
    embed.add_field(name="🏢 Подразделение", value=appeal["department"] or "Не назначено", inline=True)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("👤 Данные заявителя"), inline=False)
    embed.add_field(name="📛 ФИО", value=appeal["fio"], inline=False)
    embed.add_field(name="📞 Контакт", value=appeal["contact"], inline=False)
    embed.add_field(name="💬 Discord", value=author_mention, inline=False)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📝 Содержание"), inline=False)
    embed.add_field(name="📝 Описание", value=appeal["description"][:1024], inline=False)

    if appeal.get("clarification_text"):
        embed.add_field(name="❓ Уточнение запрошено", value=appeal["clarification_text"][:1024], inline=False)

    if appeal.get("citizen_reply_text"):
        embed.add_field(name="📩 Ответ заявителя", value=appeal["citizen_reply_text"][:1024], inline=False)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("⚙️ Служебная часть"), inline=False)
    if appeal.get("accepted_by"):
        embed.add_field(name="✅ Принял", value=f"<@{appeal['accepted_by']}>", inline=True)
    if appeal.get("assigned_to"):
        embed.add_field(name="👤 Исполнитель", value=f"<@{appeal['assigned_to']}>", inline=True)
    if appeal.get("work_channel_id"):
        embed.add_field(name="📁 Рабочий чат", value=f"<#{appeal['work_channel_id']}>", inline=True)
    if appeal.get("resolution_text"):
        embed.add_field(name="📌 Итог / причина", value=appeal["resolution_text"][:1024], inline=False)

    embed.add_field(name="📅 Создано", value=appeal["created_at"], inline=True)
    embed.add_field(name="🕒 Обновлено", value=appeal["updated_at"], inline=True)
    if appeal.get("closed_at"):
        embed.add_field(name="🏁 Завершено", value=appeal["closed_at"], inline=True)

    return style_embed(embed)


def build_history_embed(number: str, rows: list[dict]) -> disnake.Embed:
    embed = disnake.Embed(title=f"📚 История обращения № {number}", color=disnake.Color.blurple())
    if not rows:
        embed.description = "История пуста."
        return style_embed(embed)

    parts = []
    for row in rows:
        actor = row["actor_name"] or "Неизвестно"
        details = row["details"] or "—"
        parts.append(
            f"**{row['created_at']}**\n"
            f"Действие: {row['action']}\n"
            f"Кто: {actor}\n"
            f"Детали: {details}"
        )

    embed.description = "\n\n".join(parts)[:4000]
    return style_embed(embed)


def build_active_appeals_embed(appeals: list[dict]) -> disnake.Embed:
    embed = disnake.Embed(title="📋 Активные обращения", color=disnake.Color.gold())
    if not appeals:
        embed.description = "Активных обращений нет."
        return style_embed(embed)

    lines = []
    for appeal in appeals:
        work_chat = f"<#{appeal['work_channel_id']}>" if appeal.get("work_channel_id") else "нет"
        executor = f"<@{appeal['assigned_to']}>" if appeal.get("assigned_to") else "не назначен"
        priority = PRIORITY_LABELS.get(appeal.get("priority", "Обычный"), appeal.get("priority", "Обычный"))
        lines.append(
            f"**{appeal['number']}**\n"
            f"Статус: {STATUS_LABELS.get(appeal['status'], appeal['status'])}\n"
            f"Приоритет: {priority}\n"
            f"Подразделение: {appeal['department'] or '—'}\n"
            f"Исполнитель: {executor}\n"
            f"Чат: {work_chat}"
        )

    embed.description = "\n\n".join(lines)[:4000]
    return style_embed(embed)


def build_hr_embed(hr: dict) -> disnake.Embed:
    color = disnake.Color.purple()
    if hr["status"] == "Одобрено":
        color = disnake.Color.green()
    elif hr["status"] == "Отказано":
        color = disnake.Color.red()

    embed = disnake.Embed(title=f"📋 Анкета № {hr['number']}", color=color)
    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📌 Основная информация"), inline=False)
    embed.add_field(name="📊 Статус", value=hr["status"], inline=True)
    embed.add_field(name="📛 ФИО", value=hr["fio"], inline=False)
    embed.add_field(name="🎂 Возраст", value=hr["age"], inline=True)
    embed.add_field(name="🧠 Опыт", value=hr["experience"], inline=True)
    embed.add_field(name="💬 Пользователь", value=f"<@{hr['user_id']}>", inline=False)
    embed.add_field(name="📝 Мотивация", value=hr["reason"][:1024], inline=False)
    embed.add_field(name="📅 Дата подачи", value=hr["created_at"], inline=False)
    if hr.get("processed_by"):
        embed.add_field(name="✅ Обработал", value=f"<@{hr['processed_by']}>", inline=False)
    return style_embed(embed)


def build_employee_embed(employee: dict, mention: str) -> disnake.Embed:
    embed = disnake.Embed(title=f"👤 Карточка сотрудника — {employee['fio']}", color=disnake.Color.teal())

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📌 Общие данные"), inline=False)
    embed.add_field(name="💬 Discord", value=mention, inline=False)
    embed.add_field(name="🏢 Подразделение", value=employee["department"], inline=True)
    embed.add_field(name="💼 Должность", value=employee["position"], inline=True)
    embed.add_field(name="🎖 Звание", value=employee["rank_name"], inline=True)
    embed.add_field(name="📊 Статус", value=employee["status"], inline=True)
    embed.add_field(name="📅 Дата вступления", value=employee["joined_at"], inline=True)
    embed.add_field(name="🧪 Испытательный срок до", value=employee["probation_until"] or "—", inline=True)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("⚖️ Учет"), inline=False)
    embed.add_field(name="📁 Всего дел", value=str(employee["cases_count"]), inline=True)
    embed.add_field(name="✅ Закрыто дел", value=str(employee["closed_cases_count"]), inline=True)
    embed.add_field(name="⚠️ Выговоры", value=str(employee["warnings_count"]), inline=True)
    embed.add_field(name="📈 Повышения", value=str(employee["promotions_count"]), inline=True)
    embed.add_field(name="🏅 Награды", value=str(employee["rewards_count"]), inline=True)

    if employee.get("notes"):
        embed.add_field(name="📝 Примечания", value=employee["notes"][:1024], inline=False)

    return style_embed(embed)


def build_leadership_panel_embed() -> disnake.Embed:
    new_count = count_appeals_by_status("Принято")
    work_count = count_appeals_by_status("В работе")
    clarify_count = count_appeals_by_status("Требует уточнения")
    closed_count = count_appeals_by_status("Закрыто")
    hr_count = count_hr_by_status("На рассмотрении")
    due_probations = len(get_due_probations())

    embed = disnake.Embed(
        title="👑 Кабинет руководства",
        description="Краткая сводка по системе.",
        color=disnake.Color.dark_blue(),
    )
    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📨 Обращения"), inline=False)
    embed.add_field(name="🟡 Новые", value=str(new_count), inline=True)
    embed.add_field(name="🟠 В работе", value=str(work_count), inline=True)
    embed.add_field(name="🟣 Уточнение", value=str(clarify_count), inline=True)
    embed.add_field(name="🟢 Закрытые", value=str(closed_count), inline=True)

    embed.add_field(name="━━━━━━━━━━━━━━━", value=section("📋 Кадры"), inline=False)
    embed.add_field(name="📄 Анкет на рассмотрении", value=str(hr_count), inline=True)
    embed.add_field(name="🧪 Истекших испытательных", value=str(due_probations), inline=True)
    embed.add_field(name="🕒 Обновлено", value=datetime.now().strftime("%d.%m.%Y %H:%M:%S"), inline=True)
    return style_embed(embed)


# =========================
# REFRESH
# =========================

async def refresh_appeal_log_card(number: str):
    try:
        appeal = get_appeal_by_number(number)
        if not appeal or not appeal.get("log_message_id"):
            return

        channel = bot.get_channel(APPEALS_LOG_CHANNEL_ID)
        if channel is None:
            return

        message = await channel.fetch_message(appeal["log_message_id"])
        embed = build_appeal_embed(appeal, f"<@{appeal['user_id']}>")
        await message.edit(embed=embed, view=AppealLogView(number))
    except Exception as e:
        log_exception("refresh_appeal_log_card", e)


async def refresh_hr_log_card(number: str):
    try:
        hr = get_hr_request_by_number(number)
        if not hr or not hr.get("log_message_id"):
            return

        channel = bot.get_channel(HR_LOG_CHANNEL_ID)
        if channel is None:
            return

        message = await channel.fetch_message(hr["log_message_id"])
        await message.edit(embed=build_hr_embed(hr), view=HRLogView(number))
    except Exception as e:
        log_exception("refresh_hr_log_card", e)


async def sync_member_rank_role(member: disnake.Member, new_rank_name: str):
    old_roles = []
    for role_id in RANK_ROLE_IDS.values():
        role = member.guild.get_role(role_id)
        if role and role in member.roles:
            old_roles.append(role)

    if old_roles:
        await member.remove_roles(*old_roles, reason="Смена звания")

    new_role_id = RANK_ROLE_IDS.get(new_rank_name)
    if new_role_id:
        new_role = member.guild.get_role(new_role_id)
        if new_role:
            await member.add_roles(new_role, reason="Выдача звания")


# =========================
# WORK CHANNELS
# =========================

async def create_work_channel_for_appeal(
    guild: disnake.Guild,
    appeal: dict,
    department: str,
    actor: disnake.Member,
) -> disnake.TextChannel:
    if department == "СО":
        category_id = SO_CATEGORY_ID
        allowed_role_ids = SO_ROLE_IDS
        suffix = "so"
    else:
        category_id = VSO_CATEGORY_ID
        allowed_role_ids = VSO_ROLE_IDS
        suffix = "vso"

    category = guild.get_channel(category_id)
    if not isinstance(category, disnake.CategoryChannel):
        raise RuntimeError("Категория подразделения не найдена")

    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        guild.me: disnake.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            read_message_history=True,
        ),
    }

    for role_id in allowed_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

    channel_name = f"obr-{appeal['number'].split('/')[-1]}-{suffix}"
    channel = await guild.create_text_channel(
        name=sanitize_channel_name(channel_name),
        category=category,
        overwrites=overwrites,
        reason=f"Рабочий чат по обращению {appeal['number']}",
    )

    set_appeal_work_channel(appeal["number"], channel.id, department, actor.id, str(actor))
    add_appeal_history(
        appeal["number"],
        "Создан рабочий чат",
        actor.id,
        str(actor),
        f"Канал: #{channel.name} / подразделение: {department}",
    )

    updated = get_appeal_by_number(appeal["number"])
    start_embed = build_appeal_embed(updated, f"<@{updated['user_id']}>")
    await channel.send(
        content=f"Рабочий чат по обращению {appeal['number']}",
        embed=start_embed,
        view=WorkChannelView(appeal["number"]),
    )

    await send_system_log(
        guild,
        "📁 Создан рабочий чат",
        (
            f"**Обращение:** {appeal['number']}\n"
            f"**Подразделение:** {department}\n"
            f"**Канал:** {channel.mention}\n"
            f"**Кто принял:** {actor.mention}"
        ),
        color=disnake.Color.orange(),
    )
    return channel


# =========================
# MODALS
# =========================

class AppealModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(label="Тип обращения", custom_id="appeal_type", max_length=100, required=True),
            disnake.ui.TextInput(label="Ваше ФИО", custom_id="fio", max_length=150, required=True),
            disnake.ui.TextInput(label="Контакт для связи", custom_id="contact", max_length=150, required=True),
            disnake.ui.TextInput(
                label="Суть обращения",
                custom_id="description",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
                required=True,
            ),
        ]
        super().__init__(title="Подача обращения", custom_id="appeal_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            appeal = create_appeal(
                user_id=inter.author.id,
                username=str(inter.author),
                appeal_type=inter.text_values["appeal_type"].strip(),
                fio=inter.text_values["fio"].strip(),
                contact=inter.text_values["contact"].strip(),
                description=inter.text_values["description"].strip(),
            )

            channel = bot.get_channel(APPEALS_LOG_CHANNEL_ID)
            if channel is None:
                await inter.response.send_message("❌ Канал логов обращений не найден.", ephemeral=True)
                return

            msg = await channel.send(
                embed=build_appeal_embed(appeal, inter.author.mention),
                view=AppealLogView(appeal["number"]),
            )
            set_appeal_log_message_id(appeal["number"], msg.id)

            await inter.response.send_message(
                f"✅ Обращение зарегистрировано.\n**Номер:** {appeal['number']}.\nОжидайте рассмотрения.",
                ephemeral=True,
            )
        except Exception as e:
            log_exception("AppealModal.callback", e)
            await inter.response.send_message(
                "❌ Ошибка при создании обращения. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class HRModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(label="Ваше ФИО", custom_id="fio", max_length=150, required=True),
            disnake.ui.TextInput(label="Ваш возраст", custom_id="age", max_length=20, required=True),
            disnake.ui.TextInput(label="Ваш опыт", custom_id="experience", max_length=300, required=True),
            disnake.ui.TextInput(
                label="Почему хотите вступить",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
                required=True,
            ),
        ]
        super().__init__(title="Анкета на трудоустройство", custom_id="hr_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            hr = create_hr_request(
                user_id=inter.author.id,
                username=str(inter.author),
                fio=inter.text_values["fio"].strip(),
                age=inter.text_values["age"].strip(),
                experience=inter.text_values["experience"].strip(),
                reason=inter.text_values["reason"].strip(),
            )

            channel = bot.get_channel(HR_LOG_CHANNEL_ID)
            if channel is None:
                await inter.response.send_message("❌ Канал логов анкет не найден.", ephemeral=True)
                return

            msg = await channel.send(embed=build_hr_embed(hr), view=HRLogView(hr["number"]))
            set_hr_log_message_id(hr["number"], msg.id)

            await inter.response.send_message(
                f"✅ Анкета отправлена.\n**Номер:** {hr['number']}.\nОжидайте решения руководства.",
                ephemeral=True,
            )
        except Exception as e:
            log_exception("HRModal.callback", e)
            await inter.response.send_message(
                "❌ Ошибка при отправке анкеты. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class RejectAppealModal(disnake.ui.Modal):
    def __init__(self, number: str):
        self.number = number
        components = [
            disnake.ui.TextInput(
                label="Причина отказа",
                custom_id="resolution",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
                required=True,
            )
        ]
        super().__init__(title=f"Отказ — {number}", custom_id=f"reject_modal_{number}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            appeal = get_appeal_by_number(self.number)
            if not appeal:
                await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
                return
            if not appeal.get("assigned_to"):
                await inter.response.send_message("❌ Сначала назначь исполнителя.", ephemeral=True)
                return

            resolution = inter.text_values["resolution"].strip()
            close_appeal(self.number, "Отказано", resolution, inter.author.id, str(inter.author))

            updated = get_appeal_by_number(self.number)
            if updated and updated.get("work_channel_id"):
                work_channel = inter.guild.get_channel(updated["work_channel_id"])
                archive_category = inter.guild.get_channel(ARCHIVE_CATEGORY_ID)
                if isinstance(work_channel, disnake.TextChannel) and isinstance(archive_category, disnake.CategoryChannel):
                    await work_channel.edit(
                        category=archive_category,
                        name=f"arch-{work_channel.name}",
                        reason="Обращение отказано",
                    )

            await refresh_appeal_log_card(self.number)
            await send_system_log(
                inter.guild,
                "🔴 Обращение отказано",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кто отказал:** {inter.author.mention}\n"
                    f"**Причина:** {resolution}"
                ),
                color=disnake.Color.red(),
            )
            if updated:
                await send_resolution_dm(updated, "Отказано", resolution)
            await inter.response.send_message(f"❌ Обращение {self.number} отказано.", ephemeral=True)
        except Exception as e:
            log_exception("RejectAppealModal.callback", e)
            await inter.response.send_message(
                "❌ Ошибка при отказе обращения. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class CloseAppealModal(disnake.ui.Modal):
    def __init__(self, number: str):
        self.number = number
        components = [
            disnake.ui.TextInput(
                label="Итог рассмотрения",
                custom_id="resolution",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
                required=True,
            )
        ]
        super().__init__(title=f"Закрытие — {number}", custom_id=f"close_modal_{number}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            appeal = get_appeal_by_number(self.number)
            if not appeal:
                await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
                return
            if not appeal.get("assigned_to"):
                await inter.response.send_message("❌ Сначала назначь исполнителя.", ephemeral=True)
                return

            resolution = inter.text_values["resolution"].strip()
            close_appeal(self.number, "Закрыто", resolution, inter.author.id, str(inter.author))

            updated = get_appeal_by_number(self.number)
            if updated and updated.get("work_channel_id"):
                work_channel = inter.guild.get_channel(updated["work_channel_id"])
                archive_category = inter.guild.get_channel(ARCHIVE_CATEGORY_ID)
                if isinstance(work_channel, disnake.TextChannel) and isinstance(archive_category, disnake.CategoryChannel):
                    await work_channel.edit(
                        category=archive_category,
                        name=f"arch-{work_channel.name}",
                        reason="Обращение закрыто",
                    )

            await refresh_appeal_log_card(self.number)
            await send_system_log(
                inter.guild,
                "🟢 Обращение закрыто",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кто закрыл:** {inter.author.mention}\n"
                    f"**Итог:** {resolution}"
                ),
                color=disnake.Color.green(),
            )
            if updated:
                await send_resolution_dm(updated, "Закрыто", resolution)
            await inter.response.send_message(f"✅ Обращение {self.number} закрыто.", ephemeral=True)
        except Exception as e:
            log_exception("CloseAppealModal.callback", e)
            await inter.response.send_message(
                "❌ Ошибка при закрытии обращения. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class ClarificationModal(disnake.ui.Modal):
    def __init__(self, number: str):
        self.number = number
        components = [
            disnake.ui.TextInput(
                label="Что нужно уточнить",
                custom_id="clarification",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
                required=True,
            )
        ]
        super().__init__(title=f"Запрос уточнения — {number}", custom_id=f"clarify_modal_{number}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            text = inter.text_values["clarification"].strip()
            set_appeal_clarification(self.number, text, inter.author.id, str(inter.author))

            appeal = get_appeal_by_number(self.number)
            if appeal:
                await send_clarification_dm(appeal, text)

            await refresh_appeal_log_card(self.number)
            await send_system_log(
                inter.guild,
                "🟣 Запрошено уточнение",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кто запросил:** {inter.author.mention}\n"
                    f"**Текст:** {text}"
                ),
                color=disnake.Color.purple(),
            )
            await inter.response.send_message(
                f"✅ По обращению {self.number} запрошено уточнение.",
                ephemeral=True,
            )
        except Exception as e:
            log_exception("ClarificationModal.callback", e)
            await inter.response.send_message(
                "❌ Ошибка при запросе уточнения. Смотри терминал / bot.log.",
                ephemeral=True,
            )


# =========================
# VIEWS
# =========================

class AppealLogView(disnake.ui.View):
    def __init__(self, number: str):
        super().__init__(timeout=None)
        self.number = number

    @disnake.ui.button(label="🟢 Принять СО", style=disnake.ButtonStyle.green, custom_id="appeal_accept_so")
    async def accept_so(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            appeal = get_appeal_by_number(self.number)
            if not appeal:
                await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
                return
            if appeal.get("work_channel_id"):
                await inter.response.send_message("❌ Рабочий чат уже создан.", ephemeral=True)
                return

            if not has_any_role(inter.author, SO_ROLE_IDS):
                await inter.response.send_message(
                    "❌ Принять обращение в СО может только сотрудник СО или руководство.",
                    ephemeral=True,
                )
                return

            await inter.response.defer(ephemeral=True)
            channel = await create_work_channel_for_appeal(inter.guild, appeal, "СО", inter.author)
            await refresh_appeal_log_card(self.number)
            await inter.edit_original_response(
                content=f"✅ Обращение {self.number} принято в СО.\nРабочий чат: {channel.mention}"
            )
        except Exception as e:
            log_exception("AppealLogView.accept_so", e)
            try:
                if inter.response.is_done():
                    await inter.edit_original_response(
                        content="❌ Ошибка при принятии обращения. Смотри терминал / bot.log."
                    )
                else:
                    await inter.response.send_message(
                        "❌ Ошибка при принятии обращения. Смотри терминал / bot.log.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @disnake.ui.button(label="🟢 Принять ВСО", style=disnake.ButtonStyle.green, custom_id="appeal_accept_vso")
    async def accept_vso(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            appeal = get_appeal_by_number(self.number)
            if not appeal:
                await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
                return
            if appeal.get("work_channel_id"):
                await inter.response.send_message("❌ Рабочий чат уже создан.", ephemeral=True)
                return

            if not has_any_role(inter.author, VSO_ROLE_IDS):
                await inter.response.send_message(
                    "❌ Принять обращение в ВСО может только сотрудник ВСО или руководство.",
                    ephemeral=True,
                )
                return

            await inter.response.defer(ephemeral=True)
            channel = await create_work_channel_for_appeal(inter.guild, appeal, "ВСО", inter.author)
            await refresh_appeal_log_card(self.number)
            await inter.edit_original_response(
                content=f"✅ Обращение {self.number} принято в ВСО.\nРабочий чат: {channel.mention}"
            )
        except Exception as e:
            log_exception("AppealLogView.accept_vso", e)
            try:
                if inter.response.is_done():
                    await inter.edit_original_response(
                        content="❌ Ошибка при принятии обращения. Смотри терминал / bot.log."
                    )
                else:
                    await inter.response.send_message(
                        "❌ Ошибка при принятии обращения. Смотри терминал / bot.log.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @disnake.ui.button(label="❓ Запрос уточнения", style=disnake.ButtonStyle.secondary, custom_id="appeal_clarify")
    async def clarify(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(ClarificationModal(self.number))

    @disnake.ui.button(label="🔴 Отказать", style=disnake.ButtonStyle.red, custom_id="appeal_reject")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(RejectAppealModal(self.number))

    @disnake.ui.button(label="⚫ Архив", style=disnake.ButtonStyle.secondary, custom_id="appeal_archive")
    async def archive(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            archive_appeal(self.number, inter.author.id, str(inter.author))
            appeal = get_appeal_by_number(self.number)

            if appeal and appeal.get("work_channel_id"):
                work_channel = inter.guild.get_channel(appeal["work_channel_id"])
                archive_category = inter.guild.get_channel(ARCHIVE_CATEGORY_ID)
                if isinstance(work_channel, disnake.TextChannel) and isinstance(archive_category, disnake.CategoryChannel):
                    await work_channel.edit(
                        category=archive_category,
                        name=f"arch-{work_channel.name}",
                        reason="Обращение архивировано",
                    )

            await refresh_appeal_log_card(self.number)
            await send_system_log(
                inter.guild,
                "⚫ Обращение архивировано",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кто архивировал:** {inter.author.mention}"
                ),
                color=disnake.Color.dark_grey(),
            )
            await inter.response.send_message(f"📦 Обращение {self.number} архивировано.", ephemeral=True)
        except Exception as e:
            log_exception("AppealLogView.archive", e)
            await inter.response.send_message(
                "❌ Ошибка архивации. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class AssignExecutorSelect(disnake.ui.UserSelect):
    def __init__(self, number: str):
        self.number = number
        super().__init__(placeholder="Выберите исполнителя", min_values=1, max_values=1)

    async def callback(self, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            selected_user = self.values[0]
            member = inter.guild.get_member(selected_user.id)
            if member is None:
                await inter.response.send_message("❌ Участник не найден на сервере.", ephemeral=True)
                return

            is_staff, matched_roles = get_staff_match_info(member)
            if not is_staff:
                roles_text = ", ".join(get_member_role_names(member)) or "ролей нет"
                await inter.response.send_message(
                    f"❌ Можно назначить только сотрудника системы.\n\nУ участника роли: {roles_text}",
                    ephemeral=True,
                )
                return

            appeal = get_appeal_by_number(self.number)
            if not appeal:
                await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
                return
            if not appeal.get("work_channel_id"):
                await inter.response.send_message(
                    "❌ Сначала нужно принять обращение и создать рабочий чат.",
                    ephemeral=True,
                )
                return

            if appeal["department"] == "СО":
                allowed_roles = SO_ROLE_IDS
            elif appeal["department"] == "ВСО":
                allowed_roles = VSO_ROLE_IDS
            else:
                allowed_roles = STAFF_ROLE_IDS

            if not has_any_role(member, allowed_roles):
                member_roles = ", ".join(get_member_role_names(member)) or "ролей нет"
                await inter.response.send_message(
                    (
                        f"❌ Этот сотрудник не относится к выбранному подразделению.\n\n"
                        f"Подразделение обращения: {appeal['department']}\n"
                        f"Роли участника: {member_roles}"
                    ),
                    ephemeral=True,
                )
                return

            set_appeal_assigned_to(self.number, member.id)
            add_appeal_history(
                self.number,
                "Назначен исполнитель",
                inter.author.id,
                str(inter.author),
                f"Исполнитель: {member}",
            )
            await refresh_appeal_log_card(self.number)

            work_channel = inter.guild.get_channel(appeal["work_channel_id"])
            if isinstance(work_channel, disnake.TextChannel):
                embed = disnake.Embed(
                    title="👤 Назначен исполнитель",
                    description=f"По обращению **{self.number}** назначен ответственный сотрудник.",
                    color=disnake.Color.blurple(),
                )
                embed.add_field(name="Исполнитель", value=f"{member.mention} (`{member.id}`)", inline=False)
                embed.add_field(name="Назначил", value=f"{inter.author.mention} (`{inter.author.id}`)", inline=False)
                style_embed(embed)
                await work_channel.send(embed=embed)

            await send_system_log(
                inter.guild,
                "👤 Назначен исполнитель",
                (
                    f"**Обращение:** {self.number}\n"
                    f"**Исполнитель:** {member.mention}\n"
                    f"**Кто назначил:** {inter.author.mention}"
                ),
                color=disnake.Color.blurple(),
            )
            await inter.response.send_message(
                f"✅ Исполнитель назначен: {member.mention}\nСовпавшие роли: {', '.join(matched_roles)}",
                ephemeral=True,
            )
        except Exception as e:
            log_exception("AssignExecutorSelect.callback", e)
            await inter.response.send_message(
                "❌ Ошибка назначения исполнителя. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class AssignExecutorView(disnake.ui.View):
    def __init__(self, number: str):
        super().__init__(timeout=120)
        self.add_item(AssignExecutorSelect(number))


class WorkChannelView(disnake.ui.View):
    def __init__(self, number: str):
        super().__init__(timeout=None)
        self.number = number

    @disnake.ui.button(label="👤 Назначить исполнителя", style=disnake.ButtonStyle.secondary, custom_id="work_assign_executor")
    async def assign_executor(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message("Выберите исполнителя:", view=AssignExecutorView(self.number), ephemeral=True)

    @disnake.ui.button(label="❓ Запрос уточнения", style=disnake.ButtonStyle.secondary, custom_id="work_clarify")
    async def clarify(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(ClarificationModal(self.number))

    @disnake.ui.button(label="🟢 Закрыть", style=disnake.ButtonStyle.primary, custom_id="work_close")
    async def close(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(CloseAppealModal(self.number))

    @disnake.ui.button(label="🔴 Отказать", style=disnake.ButtonStyle.red, custom_id="work_reject")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(RejectAppealModal(self.number))

    @disnake.ui.button(label="⚫ Архив", style=disnake.ButtonStyle.secondary, custom_id="work_archive")
    async def archive(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
                await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
                return

            archive_appeal(self.number, inter.author.id, str(inter.author))
            appeal = get_appeal_by_number(self.number)

            if appeal and appeal.get("work_channel_id"):
                work_channel = inter.guild.get_channel(appeal["work_channel_id"])
                archive_category = inter.guild.get_channel(ARCHIVE_CATEGORY_ID)
                if isinstance(work_channel, disnake.TextChannel) and isinstance(archive_category, disnake.CategoryChannel):
                    await work_channel.edit(
                        category=archive_category,
                        name=f"arch-{work_channel.name}",
                        reason="Обращение архивировано",
                    )

            await refresh_appeal_log_card(self.number)
            await send_system_log(
                inter.guild,
                "⚫ Обращение архивировано",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кто архивировал:** {inter.author.mention}"
                ),
                color=disnake.Color.dark_grey(),
            )
            await inter.response.send_message(f"📦 Обращение {self.number} архивировано.", ephemeral=True)
        except Exception as e:
            log_exception("WorkChannelView.archive", e)
            await inter.response.send_message(
                "❌ Ошибка архивации. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class HRLogView(disnake.ui.View):
    def __init__(self, number: str):
        super().__init__(timeout=None)
        self.number = number

    @disnake.ui.button(label="✅ Принять", style=disnake.ButtonStyle.green, custom_id="hr_accept")
    async def accept(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
                await inter.response.send_message("❌ Только руководство может обрабатывать анкеты.", ephemeral=True)
                return

            hr = get_hr_request_by_number(self.number)
            if not hr:
                await inter.response.send_message("❌ Анкета не найдена.", ephemeral=True)
                return

            update_hr_status(self.number, "Одобрено", inter.author.id, str(inter.author))
            employee = create_employee(
                hr["user_id"],
                hr["fio"],
                department="СО",
                position="Стажёр",
                rank_name="Младший лейтенант юстиции",
                probation_days=PROBATION_DAYS,
            )

            member = inter.guild.get_member(hr["user_id"])
            if member:
                trainee_role = inter.guild.get_role(ROLE_TRAINEE)
                employee_role = inter.guild.get_role(EMPLOYEE_ROLE_ID)
                rank_role = inter.guild.get_role(RANK_ROLE_IDS["Младший лейтенант юстиции"])
                roles_to_add = [r for r in [trainee_role, employee_role, rank_role] if r]
                if roles_to_add:
                    await member.add_roles(*roles_to_add, reason="Принят по анкете")
                try:
                    await member.edit(nick=f"[Стажёр] {hr['fio']}")
                except Exception:
                    pass

            await refresh_hr_log_card(self.number)
            await send_system_log(
                inter.guild,
                "✅ Анкета одобрена",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кандидат:** <@{hr['user_id']}>\n"
                    f"**Кто одобрил:** {inter.author.mention}\n"
                    f"**Испытательный срок до:** {employee['probation_until']}"
                ),
                color=disnake.Color.green(),
            )
            await inter.response.send_message(f"✅ Анкета {self.number} одобрена.", ephemeral=True)
        except Exception as e:
            log_exception("HRLogView.accept", e)
            await inter.response.send_message(
                "❌ Ошибка принятия анкеты. Смотри терминал / bot.log.",
                ephemeral=True,
            )

    @disnake.ui.button(label="❌ Отказать", style=disnake.ButtonStyle.red, custom_id="hr_reject")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
                await inter.response.send_message("❌ Только руководство может обрабатывать анкеты.", ephemeral=True)
                return

            hr = get_hr_request_by_number(self.number)
            if not hr:
                await inter.response.send_message("❌ Анкета не найдена.", ephemeral=True)
                return

            update_hr_status(self.number, "Отказано", inter.author.id, str(inter.author))
            await refresh_hr_log_card(self.number)
            await send_system_log(
                inter.guild,
                "❌ Анкета отклонена",
                (
                    f"**Номер:** {self.number}\n"
                    f"**Кандидат:** <@{hr['user_id']}>\n"
                    f"**Кто отказал:** {inter.author.mention}"
                ),
                color=disnake.Color.red(),
            )
            await inter.response.send_message(f"❌ Анкета {self.number} отклонена.", ephemeral=True)
        except Exception as e:
            log_exception("HRLogView.reject", e)
            await inter.response.send_message(
                "❌ Ошибка отказа анкеты. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class ProbationView(disnake.ui.View):
    def __init__(self, discord_id: int):
        super().__init__(timeout=None)
        self.discord_id = discord_id

    @disnake.ui.button(label="✅ Завершить", style=disnake.ButtonStyle.green, custom_id="probation_finish")
    async def finish(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
                await inter.response.send_message("❌ Только руководство может завершать испытательный срок.", ephemeral=True)
                return

            employee = get_employee_by_discord_id(self.discord_id)
            if not employee:
                await inter.response.send_message("❌ Сотрудник не найден.", ephemeral=True)
                return

            update_employee_status(self.discord_id, "Действующий сотрудник")
            member = inter.guild.get_member(self.discord_id)
            if member:
                trainee_role = inter.guild.get_role(ROLE_TRAINEE)
                if trainee_role and trainee_role in member.roles:
                    await member.remove_roles(trainee_role, reason="Испытательный срок завершён")

            await inter.response.send_message("✅ Испытательный срок завершён.", ephemeral=True)
            await send_system_log(
                inter.guild,
                "✅ Испытательный срок завершён",
                (
                    f"**Сотрудник:** <@{self.discord_id}>\n"
                    f"**Кто завершил:** {inter.author.mention}"
                ),
                color=disnake.Color.green(),
            )
        except Exception as e:
            log_exception("ProbationView.finish", e)
            await inter.response.send_message(
                "❌ Ошибка завершения испытательного срока. Смотри терминал / bot.log.",
                ephemeral=True,
            )

    @disnake.ui.button(label="🔄 Продлить", style=disnake.ButtonStyle.secondary, custom_id="probation_extend")
    async def extend(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
                await inter.response.send_message("❌ Только руководство может продлевать испытательный срок.", ephemeral=True)
                return

            employee = extend_probation(self.discord_id, 3)
            if not employee:
                await inter.response.send_message("❌ Сотрудник не найден.", ephemeral=True)
                return

            await inter.response.send_message("✅ Испытательный срок продлён на 3 дня.", ephemeral=True)
            await send_system_log(
                inter.guild,
                "🔄 Испытательный срок продлён",
                (
                    f"**Сотрудник:** <@{self.discord_id}>\n"
                    f"**Новая дата:** {employee['probation_until']}\n"
                    f"**Кто продлил:** {inter.author.mention}"
                ),
                color=disnake.Color.orange(),
            )
        except Exception as e:
            log_exception("ProbationView.extend", e)
            await inter.response.send_message(
                "❌ Ошибка продления испытательного срока. Смотри терминал / bot.log.",
                ephemeral=True,
            )

    @disnake.ui.button(label="❌ Провалить", style=disnake.ButtonStyle.red, custom_id="probation_fail")
    async def fail(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
                await inter.response.send_message("❌ Только руководство может проваливать испытательный срок.", ephemeral=True)
                return

            employee = get_employee_by_discord_id(self.discord_id)
            if not employee:
                await inter.response.send_message("❌ Сотрудник не найден.", ephemeral=True)
                return

            update_employee_status(self.discord_id, "Провалил испытательный срок")
            member = inter.guild.get_member(self.discord_id)
            if member:
                trainee_role = inter.guild.get_role(ROLE_TRAINEE)
                employee_role = inter.guild.get_role(EMPLOYEE_ROLE_ID)
                roles_to_remove = [r for r in [trainee_role, employee_role] if r and r in member.roles]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="Провал испытательного срока")

            await inter.response.send_message("❌ Испытательный срок провален.", ephemeral=True)
            await send_system_log(
                inter.guild,
                "❌ Испытательный срок провален",
                (
                    f"**Сотрудник:** <@{self.discord_id}>\n"
                    f"**Кто вынес решение:** {inter.author.mention}"
                ),
                color=disnake.Color.red(),
            )
        except Exception as e:
            log_exception("ProbationView.fail", e)
            await inter.response.send_message(
                "❌ Ошибка провала испытательного срока. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class RankSelect(disnake.ui.StringSelect):
    def __init__(self, member_id: int):
        self.member_id = member_id
        options = [disnake.SelectOption(label=rank, value=rank) for rank in RANK_OPTIONS]
        super().__init__(placeholder="Выберите новое звание", options=options, min_values=1, max_values=1)

    async def callback(self, inter: disnake.MessageInteraction):
        try:
            if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
                await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
                return

            target = inter.guild.get_member(self.member_id)
            if target is None:
                await inter.response.send_message("❌ Сотрудник не найден.", ephemeral=True)
                return

            employee = get_employee_by_discord_id(target.id)
            if not employee:
                await inter.response.send_message("❌ У сотрудника нет карточки.", ephemeral=True)
                return

            new_rank = self.values[0]
            update_employee_rank(target.id, new_rank)
            await sync_member_rank_role(target, new_rank)

            await send_system_log(
                inter.guild,
                "🎖 Изменение звания",
                (
                    f"**Сотрудник:** {target.mention}\n"
                    f"**Новое звание:** {new_rank}\n"
                    f"**Кто изменил:** {inter.author.mention}"
                ),
                color=disnake.Color.blurple(),
            )
            await inter.response.send_message(
                f"✅ Звание изменено: {target.mention} → **{new_rank}**",
                ephemeral=True,
            )
        except Exception as e:
            log_exception("RankSelect.callback", e)
            await inter.response.send_message(
                "❌ Ошибка смены звания. Смотри терминал / bot.log.",
                ephemeral=True,
            )


class RankSelectView(disnake.ui.View):
    def __init__(self, member_id: int):
        super().__init__(timeout=120)
        self.add_item(RankSelect(member_id))


class PanelView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="📨 Подать обращение", style=disnake.ButtonStyle.green, custom_id="panel_appeal")
    async def send_appeal(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(AppealModal())

    @disnake.ui.button(label="📋 Подать анкету", style=disnake.ButtonStyle.blurple, custom_id="panel_hr")
    async def send_hr(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(HRModal())


# =========================
# COMMANDS
# =========================

@bot.slash_command(name="panel", description="Панель обращений и анкет", guild_ids=[GUILD_ID])
async def panel(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.author, disnake.Member) or not member_has_leader_panel_access(inter.author):
        await inter.response.send_message("❌ Доступ к /panel только для 8 и 9 ранга.", ephemeral=True)
        return
    await inter.response.send_message(embed=build_panel_embed(), view=PanelView(), ephemeral=True)


@bot.slash_command(name="appeal_find", description="Найти обращение по номеру", guild_ids=[GUILD_ID])
async def appeal_find(inter: disnake.ApplicationCommandInteraction, number: str):
    if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
        await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
        return

    appeal = get_appeal_by_number(number.strip())
    if not appeal:
        await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
        return

    embed = build_appeal_embed(appeal, f"<@{appeal['user_id']}>")
    history_embed = build_history_embed(number.strip(), get_appeal_history(number.strip(), 20))
    await inter.response.send_message(embeds=[embed, history_embed], ephemeral=True)


@bot.slash_command(name="appeals_active", description="Активные обращения", guild_ids=[GUILD_ID])
async def appeals_active(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
        await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
        return

    embed = build_active_appeals_embed(get_active_appeals(50))
    await inter.response.send_message(embed=embed, ephemeral=True)


@bot.slash_command(name="reply_clarification", description="Ответить на уточнение по обращению", guild_ids=[GUILD_ID])
async def reply_clarification(inter: disnake.ApplicationCommandInteraction, number: str, text: str):
    appeal = get_appeal_by_number(number.strip())
    if not appeal:
        await inter.response.send_message("❌ Обращение не найдено.", ephemeral=True)
        return

    if appeal["user_id"] != inter.author.id and not (
        isinstance(inter.author, disnake.Member) and member_has_staff_access(inter.author)
    ):
        await inter.response.send_message("❌ Вы не можете отвечать на это обращение.", ephemeral=True)
        return

    set_citizen_reply(number.strip(), text.strip(), inter.author.id, str(inter.author))

    updated = get_appeal_by_number(number.strip())
    if updated and updated.get("work_channel_id"):
        work_channel = bot.get_channel(updated["work_channel_id"])
        if isinstance(work_channel, disnake.TextChannel):
            embed = disnake.Embed(
                title="📩 Ответ на уточнение",
                description=f"По обращению **{number.strip()}** поступил ответ от заявителя.",
                color=disnake.Color.green(),
            )
            embed.add_field(name="Заявитель", value=f"{inter.author.mention} (`{inter.author.id}`)", inline=False)
            embed.add_field(name="Текст ответа", value=text.strip()[:1024], inline=False)
            style_embed(embed)
            await work_channel.send(embed=embed)

    await refresh_appeal_log_card(number.strip())
    await inter.response.send_message("✅ Ваш ответ по уточнению отправлен.", ephemeral=True)


@bot.slash_command(name="profile", description="Моя карточка сотрудника", guild_ids=[GUILD_ID])
async def profile(inter: disnake.ApplicationCommandInteraction):
    employee = get_employee_by_discord_id(inter.author.id)
    if not employee:
        await inter.response.send_message("❌ Карточка сотрудника не найдена.", ephemeral=True)
        return

    await inter.response.send_message(embed=build_employee_embed(employee, inter.author.mention), ephemeral=True)


@bot.slash_command(name="employee_card", description="Карточка сотрудника", guild_ids=[GUILD_ID])
async def employee_card(inter: disnake.ApplicationCommandInteraction, member: disnake.Member):
    if not isinstance(inter.author, disnake.Member) or not member_has_staff_access(inter.author):
        await inter.response.send_message("❌ У вас нет доступа.", ephemeral=True)
        return

    employee = get_employee_by_discord_id(member.id)
    if not employee:
        await inter.response.send_message(
            "❌ Карточка сотрудника не найдена. Создай её в веб-панели или через /create_employee_card",
            ephemeral=True,
        )
        return

    await inter.response.send_message(embed=build_employee_embed(employee, member.mention), ephemeral=True)


@bot.slash_command(name="create_employee_card", description="Создать карточку сотрудника вручную", guild_ids=[GUILD_ID])
async def create_employee_card(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member,
    fio: str,
    department: str = "СО",
    position: str = "Стажёр",
):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
        return

    if department not in {"СО", "ВСО"}:
        await inter.response.send_message("❌ Допустимые подразделения: СО, ВСО.", ephemeral=True)
        return

    existing = get_employee_by_discord_id(member.id)
    if existing:
        await inter.response.send_message("❌ У сотрудника уже есть карточка.", ephemeral=True)
        return

    employee = create_employee(
        member.id,
        fio,
        department=department,
        position=position,
        rank_name="Младший лейтенант юстиции",
        probation_days=PROBATION_DAYS,
    )

    trainee_role = inter.guild.get_role(ROLE_TRAINEE)
    employee_role = inter.guild.get_role(EMPLOYEE_ROLE_ID)
    rank_role = inter.guild.get_role(RANK_ROLE_IDS["Младший лейтенант юстиции"])

    roles_to_add = [r for r in [trainee_role, employee_role, rank_role] if r]
    if roles_to_add:
        await member.add_roles(*roles_to_add, reason="Создание карточки сотрудника")

    try:
        await member.edit(nick=f"[Стажёр] {fio}")
    except Exception:
        pass

    await send_system_log(
        inter.guild,
        "👤 Создана карточка сотрудника",
        (
            f"**Сотрудник:** {member.mention}\n"
            f"**ФИО:** {fio}\n"
            f"**Подразделение:** {department}\n"
            f"**Кто создал:** {inter.author.mention}"
        ),
        color=disnake.Color.teal(),
    )
    await inter.response.send_message(embed=build_employee_embed(employee, member.mention), ephemeral=True)


@bot.slash_command(name="set_rank_select", description="Изменить звание сотрудника", guild_ids=[GUILD_ID])
async def set_rank_select(inter: disnake.ApplicationCommandInteraction, member: disnake.Member):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
        return

    employee = get_employee_by_discord_id(member.id)
    if not employee:
        await inter.response.send_message("❌ У сотрудника нет карточки.", ephemeral=True)
        return

    await inter.response.send_message(
        f"Выберите новое звание для {member.mention}:",
        view=RankSelectView(member.id),
        ephemeral=True,
    )


@bot.slash_command(name="punish", description="Выдать дисциплинарную меру", guild_ids=[GUILD_ID])
async def punish(inter: disnake.ApplicationCommandInteraction, member: disnake.Member, action_type: str, reason: str):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
        return

    employee = get_employee_by_discord_id(member.id)
    if not employee:
        await inter.response.send_message("❌ У сотрудника нет карточки.", ephemeral=True)
        return

    allowed = {"Выговор", "Строгий выговор", "Предупреждение"}
    if action_type not in allowed:
        await inter.response.send_message(
            "❌ Допустимые типы: Выговор, Строгий выговор, Предупреждение.",
            ephemeral=True,
        )
        return

    record = add_discipline_record(member.id, employee["fio"], action_type, reason, inter.author.id, str(inter.author))
    await inter.response.send_message(f"✅ Дисциплинарная мера выдана: {record['number']}", ephemeral=True)
    await send_system_log(
        inter.guild,
        "⚖️ Дисциплинарная мера",
        (
            f"**Номер:** {record['number']}\n"
            f"**Сотрудник:** {member.mention}\n"
            f"**Тип:** {action_type}\n"
            f"**Причина:** {reason}\n"
            f"**Кто выдал:** {inter.author.mention}"
        ),
        color=disnake.Color.red(),
    )


@bot.slash_command(name="leadership_panel", description="Кабинет руководства", guild_ids=[GUILD_ID])
async def leadership_panel(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
        return

    await inter.response.send_message(embed=build_leadership_panel_embed(), ephemeral=True)


@bot.slash_command(name="make_backup", description="Сделать резервную копию базы", guild_ids=[GUILD_ID])
async def make_backup(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Доступ только для 8 и 9 ранга.", ephemeral=True)
        return

    try:
        path = backup_database()
        await inter.response.send_message(f"✅ Бэкап создан:\n`{path}`", ephemeral=True)
    except Exception as e:
        log_exception("make_backup", e)
        await inter.response.send_message("❌ Ошибка создания бэкапа.", ephemeral=True)


@bot.slash_command(name="debug_roles", description="Показать системные роли бота", guild_ids=[GUILD_ID])
async def debug_roles(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Только руководство может использовать debug.", ephemeral=True)
        return

    lines = [
        f"ROLE_LEADER = {ROLE_LEADER}",
        f"ROLE_DEPUTY = {ROLE_DEPUTY}",
        f"ROLE_SO_HEAD = {ROLE_SO_HEAD}",
        f"ROLE_VSO_HEAD = {ROLE_VSO_HEAD}",
        f"ROLE_SO = {ROLE_SO}",
        f"ROLE_VSO = {ROLE_VSO}",
        f"ROLE_INVESTIGATOR = {ROLE_INVESTIGATOR}",
        f"ROLE_CRIMINALIST = {ROLE_CRIMINALIST}",
        f"ROLE_TRAINEE = {ROLE_TRAINEE}",
        f"EMPLOYEE_ROLE_ID = {EMPLOYEE_ROLE_ID}",
        "",
        "STAFF_ROLE_IDS:",
    ]

    for role_id in STAFF_ROLE_IDS:
        role = inter.guild.get_role(role_id)
        role_name = role.name if role else "НЕ НАЙДЕНА НА СЕРВЕРЕ"
        lines.append(f"- {role_id} | {role_name}")

    embed = disnake.Embed(
        title="🛠 Debug системных ролей",
        description="```" + "\n".join(lines)[:3800] + "```",
        color=disnake.Color.orange(),
    )
    await inter.response.send_message(embed=embed, ephemeral=True)


@bot.slash_command(name="debug_member", description="Проверить роли участника", guild_ids=[GUILD_ID])
async def debug_member(inter: disnake.ApplicationCommandInteraction, member: disnake.Member):
    if not isinstance(inter.author, disnake.Member) or not member_has_hr_access(inter.author):
        await inter.response.send_message("❌ Только руководство может использовать debug.", ephemeral=True)
        return

    ok, matched = get_staff_match_info(member)
    embed = disnake.Embed(
        title=f"🛠 Debug участника — {member}",
        color=disnake.Color.green() if ok else disnake.Color.red(),
    )
    embed.add_field(name="Подходит как сотрудник?", value="✅ Да" if ok else "❌ Нет", inline=False)
    embed.add_field(
        name="Совпавшие системные роли",
        value="\n".join(matched) if matched else "Совпадений нет",
        inline=False,
    )

    roles_text = "\n".join([f"- {role.name} ({role.id})" for role in member.roles]) or "Ролей нет"
    if len(roles_text) > 1024:
        roles_text = roles_text[:1000] + "\n..."
    embed.add_field(name="Все роли участника", value=roles_text, inline=False)

    await inter.response.send_message(embed=embed, ephemeral=True)


# =========================
# TASKS
# =========================

@tasks.loop(minutes=30)
async def check_stuck_appeals():
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM appeals WHERE status = 'Принято' AND archive_flag = 0"
            ).fetchall()

        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return

        for row in rows:
            created = datetime.strptime(row["created_at"], "%d.%m.%Y %H:%M:%S")
            if (datetime.now() - created).total_seconds() >= REMINDER_HOURS * 3600:
                await send_system_log(
                    guild,
                    "⏰ Зависшее обращение",
                    (
                        f"**Номер:** {row['number']}\n"
                        f"**Статус:** {row['status']}\n"
                        f"Никто не взял обращение в работу более {REMINDER_HOURS} часов."
                    ),
                    color=disnake.Color.red(),
                )
    except Exception as e:
        log_exception("check_stuck_appeals", e)


@tasks.loop(hours=1)
async def check_probations():
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return

        due = get_due_probations()
        for employee in due:
            await send_system_log(
                guild,
                "🧪 Испытательный срок истёк",
                (
                    f"**Сотрудник:** <@{employee['discord_id']}>\n"
                    f"**ФИО:** {employee['fio']}\n"
                    f"**Дата окончания:** {employee['probation_until']}\n"
                    f"Требуется решение руководства."
                ),
                color=disnake.Color.orange(),
                view=ProbationView(employee["discord_id"]),
            )
    except Exception as e:
        log_exception("check_probations", e)


# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    try:
        init_db()
        bot.add_view(PanelView())

        if not check_stuck_appeals.is_running():
            check_stuck_appeals.start()
        if not check_probations.is_running():
            check_probations.start()

        guild = bot.get_guild(GUILD_ID)
        if guild:
            startup_debug(guild)

        logger.info("Бот запущен как %s", bot.user)
    except Exception as e:
        log_exception("on_ready", e)


@bot.event
async def on_slash_command_error(inter, error):
    log_exception("on_slash_command_error", error)
    try:
        if inter.response.is_done():
            await inter.followup.send(
                "❌ Произошла ошибка. Проверь терминал / bot.log.",
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                "❌ Произошла ошибка. Проверь терминал / bot.log.",
                ephemeral=True,
            )
    except Exception:
        pass


@bot.event
async def on_button_click(inter):
    logger.info(
        "Нажата кнопка: %s | user=%s",
        getattr(inter.component, "custom_id", "unknown"),
        inter.author,
    )


bot.run(TOKEN)
