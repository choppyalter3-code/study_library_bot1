import asyncio
import logging
import os
import re
import time
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ----------------------------
# Конфигурация и логирование
# ----------------------------

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USER_ID_RAW: str = os.getenv("ADMIN_USER_ID", "").strip()
PORT: int = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL: str = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "telegram")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "").strip()

if not RENDER_EXTERNAL_URL:
    raise RuntimeError("Не найден RENDER_EXTERNAL_URL в .env / Environment Variables")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_BOT_TOKEN в .env")

if not ADMIN_USER_ID_RAW.isdigit():
    raise RuntimeError("ADMIN_USER_ID в .env должен быть числом (user id в Telegram)")

ADMIN_USER_ID: int = int(ADMIN_USER_ID_RAW)

DATABASE_PATH: str = os.path.join(os.path.dirname(__file__), "study_library.sqlite3")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("study_library_bot")


# ----------------------------
# Модель данных
# ----------------------------

@dataclass
class Category:
    category_id: int
    name: str
    icon: str
    sort_order: int


@dataclass
class Material:
    material_id: int
    category_id: int
    title: str
    description: str
    link: str
    tags: str
    file_id: str
    created_at_iso: str


# ----------------------------
# Работа с базой SQLite
# ----------------------------

class Database:
    def get_category_by_name(self, category_name: str) -> Optional[Category]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT category_id, name, icon, sort_order
                FROM categories
                WHERE lower(name) = lower(?)
                LIMIT 1
                """,
                (category_name.strip(),),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            return Category(
                category_id=int(row["category_id"]),
                name=str(row["name"]),
                icon=str(row["icon"]),
                sort_order=int(row["sort_order"]),
            )
        finally:
            connection.close()

    def upsert_destination(
        self,
        category_id: int,
        chat_id: int,
        thread_id: int,
        title: str,
    ) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                DELETE FROM destinations
                WHERE category_id = ?
                """,
                (category_id,),
            )

            cursor.execute(
                """
                INSERT INTO destinations(category_id, chat_id, thread_id, title)
                VALUES (?, ?, ?, ?)
                """,
                (category_id, chat_id, thread_id, title),
            )

            connection.commit()
        finally:
            connection.close()

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_database(self) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    icon TEXT NOT NULL,
                    sort_order INTEGER NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS materials (
                    material_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    link TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (category_id) REFERENCES categories(category_id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS destinations (
                    destination_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    title TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS deadlines (
                    deadline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    deadline_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            cursor.execute(
                "INSERT OR IGNORE INTO admins(user_id) VALUES (?)",
                (ADMIN_USER_ID,),
            )

            cursor.execute("SELECT COUNT(*) AS c FROM categories")
            count = int(cursor.fetchone()["c"])

            if count == 0:
                starter_categories = [
                    ("Объявления", "📢", 1),
                    ("Лекции", "📚", 2),
                    ("Домашки", "📝", 3),
                    ("Материалы", "📂", 4),
                    ("Дедлайны", "📅", 5),
                    ("Экзамен", "🧠", 6),
                    ("Полезные ссылки", "🔗", 7),
                ]
                cursor.executemany(
                    "INSERT INTO categories(name, icon, sort_order) VALUES (?, ?, ?)",
                    starter_categories,
                )

            connection.commit()
        finally:
            connection.close()

    def is_admin(self, user_id: int) -> bool:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None
        finally:
            connection.close()

    def upsert_group(self, chat_id: int, title: str) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO groups(chat_id, title, registered_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title
                """,
                (chat_id, title, datetime.utcnow().isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def list_groups(self) -> List[Tuple[int, str]]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT chat_id, title FROM groups ORDER BY registered_at DESC"
            )
            rows = cursor.fetchall()
            return [(int(row["chat_id"]), str(row["title"])) for row in rows]
        finally:
            connection.close()

    def get_destination_for_category(self, category_id: int):
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT chat_id, thread_id
                FROM destinations
                WHERE category_id = ?
                LIMIT 1
                """,
                (category_id,),
            )
            row = cursor.fetchone()
            if row:
                return int(row["chat_id"]), int(row["thread_id"])
            return None
        finally:
            connection.close()

    def list_categories(self) -> List[Category]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT category_id, name, icon, sort_order FROM categories ORDER BY sort_order ASC, name ASC"
            )
            rows = cursor.fetchall()
            categories: List[Category] = []
            for row in rows:
                categories.append(
                    Category(
                        category_id=int(row["category_id"]),
                        name=str(row["name"]),
                        icon=str(row["icon"]),
                        sort_order=int(row["sort_order"]),
                    )
                )
            return categories
        finally:
            connection.close()

    def get_category(self, category_id: int) -> Optional[Category]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT category_id, name, icon, sort_order FROM categories WHERE category_id = ?",
                (category_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Category(
                category_id=int(row["category_id"]),
                name=str(row["name"]),
                icon=str(row["icon"]),
                sort_order=int(row["sort_order"]),
            )
        finally:
            connection.close()

    def add_material(
        self,
        category_id: int,
        title: str,
        description: str,
        link: str,
        tags: str,
        file_id: str,
    ) -> int:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            created_at = datetime.utcnow().isoformat()
            cursor.execute(
                """
                INSERT INTO materials(category_id, title, description, link, tags, file_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (category_id, title, description, link, tags, file_id, created_at),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def add_deadline(self, text: str, deadline_date: str):

        connection = self._get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO deadlines(text, deadline_date, created_at)
                VALUES (?, ?, ?)
                """,
                (text, deadline_date, datetime.utcnow().isoformat()),
            )

            connection.commit()

        finally:
            connection.close()

    def list_deadlines(self):

        connection = self._get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT deadline_id, text, deadline_date
                FROM deadlines
                ORDER BY deadline_date ASC
                """
            )

            rows = cursor.fetchall()

            return rows

        finally:
            connection.close()
            
    def list_materials_by_category(self, category_id: int) -> List[Material]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                FROM materials
                WHERE category_id = ?
                ORDER BY material_id DESC
                """,
                (category_id,),
            )
            rows = cursor.fetchall()
            materials: List[Material] = []
            for row in rows:
                materials.append(
                    Material(
                        material_id=int(row["material_id"]),
                        category_id=int(row["category_id"]),
                        title=str(row["title"]),
                        description=str(row["description"]),
                        link=str(row["link"]),
                        tags=str(row["tags"]),
                        file_id=str(row["file_id"]),
                        created_at_iso=str(row["created_at"]),
                    )
                )
            return materials
        finally:
            connection.close()

    def get_material(self, material_id: int) -> Optional[Material]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                FROM materials
                WHERE material_id = ?
                """,
                (material_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return Material(
                material_id=int(row["material_id"]),
                category_id=int(row["category_id"]),
                title=str(row["title"]),
                description=str(row["description"]),
                link=str(row["link"]),
                tags=str(row["tags"]),
                file_id=str(row["file_id"]),
                created_at_iso=str(row["created_at"]),
            )
        finally:
            connection.close()

    def search_materials(self, query: str, limit: int = 20) -> List[Material]:
        q = f"%{query.strip().lower()}%"
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                FROM materials
                WHERE lower(title) LIKE ?
                   OR lower(description) LIKE ?
                   OR lower(tags) LIKE ?
                ORDER BY material_id DESC
                LIMIT ?
                """,
                (q, q, q, limit),
            )
            rows = cursor.fetchall()
            results: List[Material] = []
            for row in rows:
                results.append(
                    Material(
                        material_id=int(row["material_id"]),
                        category_id=int(row["category_id"]),
                        title=str(row["title"]),
                        description=str(row["description"]),
                        link=str(row["link"]),
                        tags=str(row["tags"]),
                        file_id=str(row["file_id"]),
                        created_at_iso=str(row["created_at"]),
                    )
                )
            return results
        finally:
            connection.close()
db = Database(DATABASE_PATH)

# ----------------------------
# Утилиты
# ----------------------------

def is_private_chat(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    return update.effective_chat.type == "private"


def format_material_text(material: Material) -> str:

    safe_title = escape_html(material.title)
    safe_desc = escape_html(material.description)
    safe_tags = escape_html(material.tags)
    safe_link = escape_html(material.link)

    category = db.get_category(material.category_id)

    if category:
        icon = category.icon
        name = category.name
    else:
        icon = "📂"
        name = "Материалы"

    lines = [
        f"{icon} <b>{name}</b>",
        "",
        f"<b>{safe_title}</b>",
        "",
        f"{safe_desc}",
        "",
        f"🔗 {safe_link}",
        f"🏷 {safe_tags}",
    ]

    return "\n".join(lines)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def normalize_tags(raw: str) -> str:
    # Принимаем: "матан, #экзамен  тензоры"
    # Превращаем в: "#матан #экзамен #тензоры"
    tokens = re.split(r"[,\s]+", raw.strip())
    cleaned: List[str] = []
    for token in tokens:
        t = token.strip()
        if not t:
            continue
        if t.startswith("#"):
            t = t[1:]
        t = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]+", "", t)
        if not t:
            continue
        cleaned.append(f"#{t.lower()}")
    if not cleaned:
        return "#без_тегов"
    # Уникализируем с сохранением порядка
    unique: List[str] = []
    seen = set()
    for item in cleaned:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return " ".join(unique)


# ----------------------------
# Меню (кнопки)
# ----------------------------

def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📚 Библиотека", callback_data="MENU_LIBRARY")],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="MENU_SEARCH")],
    ]

    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text="➕ Добавить материал", callback_data="MENU_ADD")]
        )

    return InlineKeyboardMarkup(keyboard)


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="MENU_MAIN")]]
    return InlineKeyboardMarkup(keyboard)


def categories_keyboard() -> InlineKeyboardMarkup:
    categories = db.list_categories()
    keyboard: List[List[InlineKeyboardButton]] = []
    for category in categories:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{category.icon} {category.name}",
                    callback_data=f"CATEGORY_{category.category_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(keyboard)


def materials_keyboard(category_id: int) -> InlineKeyboardMarkup:

    materials = db.list_materials_by_category(category_id)

    keyboard: List[List[InlineKeyboardButton]] = []

    if not materials:
        keyboard.append(
            [InlineKeyboardButton(text="(Материалов пока нет)", callback_data="NOOP")]
        )
    else:
        for material in materials[:30]:
            title = material.title if material.title else "Без названия"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=title[:45],
                        callback_data=f"MATERIAL_{material.material_id}",
                    )
                ]
            )

    keyboard.append(
        [
            InlineKeyboardButton(text="⬅️ К категориям", callback_data="MENU_LIBRARY"),
            InlineKeyboardButton(text="🏠 В меню", callback_data="MENU_MAIN"),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def material_view_keyboard(material_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []

    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text="📣 Отправить в группу", callback_data=f"SEND_{material_id}")]
        )

    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="BACK_FROM_MATERIAL")])
    keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="MENU_MAIN")])

    return InlineKeyboardMarkup(keyboard)


def groups_keyboard(material_id: int) -> InlineKeyboardMarkup:
    groups = db.list_groups()
    keyboard: List[List[InlineKeyboardButton]] = []
    if not groups:
        keyboard.append([InlineKeyboardButton(text="(Группы не зарегистрированы)", callback_data="NOOP")])
    else:
        for chat_id, title in groups[:20]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=title[:45],
                        callback_data=f"SENDTO_{material_id}_{chat_id}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"MATERIAL_{material_id}")])
    return InlineKeyboardMarkup(keyboard)


# ----------------------------
# Conversation states (добавление / поиск)
# ----------------------------

ADD_CATEGORY = 1
ADD_TITLE = 2
ADD_DESCRIPTION = 3
ADD_LINK = 4
ADD_TAGS = 5
ADD_FILE = 6

SEARCH_WAIT_QUERY = 10


# ----------------------------
# Проверка прав
# ----------------------------

def require_admin(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return db.is_admin(user.id)


async def deny_if_not_admin(update: Update) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text("Доступ только для администратора.")


# ----------------------------
# Хендлеры команд
# ----------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    if not is_private_chat(update):
        return

    is_admin = require_admin(update)

    await update.effective_message.reply_text(
        "Главное меню:",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def register_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Команда вызывается в группе, чтобы бот запомнил chat_id
    if update.effective_chat is None or update.effective_message is None:
        return

    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("Эта команда нужна в группе.")
        return

    if not require_admin(update):
        # В группе не спорим — просто молчим
        return

    title = update.effective_chat.title or "Без названия"
    db.upsert_group(update.effective_chat.id, title)

    await update.effective_message.reply_text(
        f"Группа зарегистрирована: {title}\nТеперь можно отправлять сюда материалы из меню бота."
    )


async def bind_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    if not require_admin(update):
        return

    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "Эту команду нужно писать в теме группы, а не в личке."
        )
        return

    if update.effective_message.message_thread_id is None:
        await update.effective_message.reply_text(
            "Эту команду нужно писать внутри конкретной темы форума."
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Использование: /bind_category Домашки"
        )
        return

    category_name = " ".join(context.args).strip()
    category = db.get_category_by_name(category_name)

    if category is None:
        await update.effective_message.reply_text(
            f"Категория '{category_name}' не найдена."
        )
        return

    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id
    topic_title = f"{category.name} → thread {thread_id}"

    db.upsert_destination(
        category_id=category.category_id,
        chat_id=chat_id,
        thread_id=thread_id,
        title=topic_title,
    )

    await update.effective_message.reply_text(
        f"Готово ✅\nКатегория '{category.name}' теперь привязана к этой теме."
    )


async def deadline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if update.effective_message is None:
        return

    if not require_admin(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Использование:\n/deadline 15.03 Лабораторная №3"
        )
        return

    deadline_date = context.args[0]
    text = " ".join(context.args[1:]).strip()

    if not text:
        await update.effective_message.reply_text(
            "Напиши описание дедлайна."
        )
        return

    db.add_deadline(text, deadline_date)

    deadline_message = (
        f"📅 <b>Дедлайн</b>\n\n"
        f"{escape_html(text)}\n"
        f"Сдать до: <b>{escape_html(deadline_date)}</b>"
    )

    # пытаемся отправить в тему категории "Дедлайны"
    category = db.get_category_by_name("Дедлайны")

    if category is not None:
        destination = db.get_destination_for_category(category.category_id)

        if destination:
            chat_id, thread_id = destination

            try:
                await context.application.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=deadline_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as error:
                logger.error("Ошибка отправки дедлайна в тему: %s", error)

    await update.effective_message.reply_text(
        deadline_message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

async def check_deadlines(application: Application):

    deadlines = db.list_deadlines()

    if not deadlines:
        return

    now = datetime.utcnow()

    for row in deadlines:

        text = row["text"]
        date_str = row["deadline_date"]

        try:
            deadline_date = datetime.strptime(date_str, "%d.%m")
            deadline_date = deadline_date.replace(year=now.year)
        except:
            continue

        delta = deadline_date - now

        if 0 < delta.total_seconds() < 86400:

            category = db.get_category_by_name("Дедлайны")

            if category is None:
                continue

            destination = db.get_destination_for_category(category.category_id)

            if not destination:
                continue

            chat_id, thread_id = destination

            message = (
                f"⚠️ <b>Напоминание о дедлайне</b>\n\n"
                f"{escape_html(text)}\n"
                f"Сдать до: <b>{escape_html(date_str)}</b>"
            )

            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as error:
                logger.error("Ошибка напоминания о дедлайне: %s", error)

async def deadlines_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if update.effective_message is None:
        return

    deadlines = db.list_deadlines()

    if not deadlines:
        await update.effective_message.reply_text(
            "📅 Пока нет сохранённых дедлайнов."
        )
        return

    lines = ["📅 <b>Ближайшие дедлайны</b>\n"]

    for row in deadlines:
        text = escape_html(row["text"])
        date = escape_html(row["deadline_date"])

        lines.append(f"• {text} — <b>{date}</b>")

    message = "\n".join(lines)

    await update.effective_message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
    )


# ----------------------------
# Меню через callback-кнопки
# ----------------------------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    if not is_private_chat(update):
        return

    is_admin = require_admin(update)
    data = query.data or ""

    if data == "MENU_MAIN":
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return

    if data == "MENU_LIBRARY":
        await query.edit_message_text(
            "Выбери вкладку/категорию:",
            reply_markup=categories_keyboard(),
        )
        return

    if data == "MENU_SEARCH":
        await query.edit_message_text(
            "Напиши запрос (слова или #теги). Например:\n"
            "матан\n"
            "#экзамен\n"
            "интеграл #матан",
            reply_markup=back_to_main_keyboard(),
        )
        context.user_data["awaiting_search_text"] = True
        return

    if data == "MENU_ADD":
        if not is_admin:
            await query.answer(
                "Только администратор может добавлять материалы",
                show_alert=True,
            )
            return

        categories = db.list_categories()
        keyboard: List[List[InlineKeyboardButton]] = []
        for category in categories:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"{category.icon} {category.name}",
                        callback_data=f"ADD_PICKCAT_{category.category_id}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="MENU_MAIN")])

        await query.edit_message_text(
            "Куда добавляем материал? Выбери категорию:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("CATEGORY_"):
        category_id = int(data.replace("CATEGORY_", "").strip())
        category = db.get_category(category_id)
        if category is None:
            await query.edit_message_text(
                "Категория не найдена.",
                reply_markup=categories_keyboard(),
            )
            return

        context.user_data["last_category_id"] = category_id
        await query.edit_message_text(
            f"{category.icon} {category.name}\nМатериалы:",
            reply_markup=materials_keyboard(category_id),
        )
        return

    if data.startswith("MATERIAL_"):
        material_id = int(data.replace("MATERIAL_", "").strip())
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        context.user_data["last_material_category_id"] = material.category_id

        await query.edit_message_text(
            format_material_text(material),
            parse_mode=ParseMode.HTML,
            reply_markup=material_view_keyboard(material.material_id, is_admin=is_admin),
            disable_web_page_preview=True,
        )
        return

    if data == "BACK_FROM_MATERIAL":
        category_id = int(context.user_data.get("last_material_category_id", 0))
        if category_id <= 0:
            await query.edit_message_text(
                "Выбери категорию:",
                reply_markup=categories_keyboard(),
            )
            return

        category = db.get_category(category_id)
        name = category.name if category else "Категория"
        icon = category.icon if category else "📚"

        await query.edit_message_text(
            f"{icon} {name}\nМатериалы:",
            reply_markup=materials_keyboard(category_id),
        )
        return

    if data.startswith("SEND_"):
        if not is_admin:
            await query.answer(
                "Только администратор может отправлять материалы в группу",
                show_alert=True,
            )
            return

        material_id = int(data.replace("SEND_", "").strip())
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        await query.edit_message_text(
            "Куда отправляем? Выбери группу:",
            reply_markup=groups_keyboard(material_id),
        )
        return

    if data.startswith("SENDTO_"):
        if not is_admin:
            await query.answer(
                "Только администратор может отправлять материалы в группу",
                show_alert=True,
            )
            return

        parts = data.split("_", 2)
        if len(parts) != 3:
            await query.edit_message_text(
                "Некорректная кнопка.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        material_id = int(parts[1])
        chat_id = int(parts[2])

        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        try:
            await send_material_to_chat(
                application=context.application,
                chat_id=chat_id,
                material=material,
            )
        except Exception as exc:
            logger.exception("Ошибка отправки в группу: %s", exc)
            await query.edit_message_text(
                "Не смог отправить в группу. Проверь, что бот добавлен в группу и у него есть право писать.",
                reply_markup=material_view_keyboard(material_id, is_admin=is_admin),
            )
            return

        await query.edit_message_text(
            "Отправлено ✅",
            reply_markup=material_view_keyboard(material_id, is_admin=is_admin),
        )
        return

    if data.startswith("ADD_PICKCAT_"):
        if not is_admin:
            await query.answer(
                "Только администратор может добавлять материалы",
                show_alert=True,
            )
            return

        category_id = int(data.replace("ADD_PICKCAT_", "").strip())
        category = db.get_category(category_id)
        if category is None:
            await query.edit_message_text(
                "Категория не найдена.",
                reply_markup=categories_keyboard(),
            )
            return

        context.user_data["add_category_id"] = category_id
        context.user_data["add_file_id"] = ""
        context.user_data["add_link"] = ""
        context.user_data["add_tags"] = ""

        await query.edit_message_text(
            f"Категория: {category.icon} {category.name}\n\nТеперь пришли заголовок материала одним сообщением.",
            reply_markup=back_to_main_keyboard(),
        )
        context.user_data["awaiting_add_title"] = True
        return

    if data == "NOOP":
        return


# ----------------------------
# Добавление материала: текстовые шаги
# ----------------------------

async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:

    results = db.search_materials(text, limit=10)

    if not results:
        await update.effective_message.reply_text(
            "Ничего не найдено.\n\nПопробуй:\n"
            "матан\n"
            "#экзамен\n"
            "интеграл"
        )
        return

    for material in results:

        await update.effective_message.reply_text(
            format_material_text(material),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return

    if not is_private_chat(update):
        return

    text = (update.effective_message.text or "").strip()
    if not text:
        return

    is_admin = require_admin(update)

    # Поиск доступен всем
    if context.user_data.get("awaiting_search_text") is True:
        context.user_data["awaiting_search_text"] = False
        await handle_search_text(update, context, text)
        return

    # Всё ниже — только для админа
    if not is_admin:
        await handle_search_text(update, context, text)
        return

    # Последний шаг добавления: если файла нет и пользователь написал "-"
    if context.user_data.get("awaiting_add_file") is True and text == "-":
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id="")
        return

    # Добавление: заголовок
    if context.user_data.get("awaiting_add_title") is True:
        context.user_data["awaiting_add_title"] = False
        context.user_data["add_title"] = text
        await update.effective_message.reply_text(
            "Отлично. Теперь пришли описание (можно коротко, 1–5 строк)."
        )
        context.user_data["awaiting_add_description"] = True
        return

    # Добавление: описание
    if context.user_data.get("awaiting_add_description") is True:
        context.user_data["awaiting_add_description"] = False
        context.user_data["add_description"] = text
        await update.effective_message.reply_text(
            "Теперь пришли ссылку (если ссылки нет — напиши: - )"
        )
        context.user_data["awaiting_add_link"] = True
        return

    # Добавление: ссылка
    if context.user_data.get("awaiting_add_link") is True:
        context.user_data["awaiting_add_link"] = False
        link = text
        if link == "-":
            link = ""
        context.user_data["add_link"] = link
        await update.effective_message.reply_text(
            "Теперь теги (через пробел или запятую). Например: матан, экзамен, интеграл"
        )
        context.user_data["awaiting_add_tags"] = True
        return

    # Добавление: теги
    if context.user_data.get("awaiting_add_tags") is True:
        context.user_data["awaiting_add_tags"] = False
        tags = normalize_tags(text)
        context.user_data["add_tags"] = tags
        await update.effective_message.reply_text(
            "Последний шаг: пришли файл (документом) или напиши: - (если без файла)"
        )
        context.user_data["awaiting_add_file"] = True
        return

    await update.effective_message.reply_text(
        "Я понимаю команды через кнопки. Открой меню:",
        reply_markup=main_menu_keyboard(is_admin=True),
    )


# ----------------------------
# Добавление материала: приём файла
# ----------------------------

async def file_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return

    if not is_private_chat(update):
        return

    if not require_admin(update):
        return

    if context.user_data.get("awaiting_add_file") is not True:
        return

    message: Message = update.effective_message

    # Если отправили документ
    if message.document is not None:
        file_id = message.document.file_id
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id=file_id)
        return

    # Если прислали не документ
    await update.effective_message.reply_text(
        "Нужен файл как документ, или напиши '-' чтобы добавить без файла."
    )


async def finalize_add_material(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str) -> None:
    category_id = int(context.user_data.get("add_category_id", 0))
    title = str(context.user_data.get("add_title", "")).strip()
    description = str(context.user_data.get("add_description", "")).strip()
    link = str(context.user_data.get("add_link", "")).strip()
    tags = str(context.user_data.get("add_tags", "")).strip()

    if not link:
        link = "—"

    if category_id <= 0 or not title or not description or not tags:
        await update.effective_message.reply_text(
            "Не хватает данных для сохранения. Давай начнём заново: /start"
        )
        return

    material_id = db.add_material(
        category_id=category_id,
        title=title,
        description=description,
        link=link,
        tags=tags,
        file_id=file_id or "",
    )

    destination = db.get_destination_for_category(category_id)

    if destination:
        chat_id, thread_id = destination

        try:
            material = db.get_material(material_id)

            if material is not None:
                await context.application.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=format_material_text(material),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )

                if material.file_id.strip():
                    await context.application.bot.send_document(
                        chat_id=chat_id,
                        message_thread_id=thread_id,
                        document=material.file_id.strip(),
                        caption=material.title,
                    )

        except Exception as error:
            logger.error("Ошибка автоотправки: %s", error)

    await update.effective_message.reply_text(
        f"Сохранено ✅ (ID: {material_id})",
        reply_markup=main_menu_keyboard(is_admin=True),
    )


# ----------------------------
# Отправка материала в чат/группу
# ----------------------------

async def send_material_to_chat(application: Application, chat_id: int, material: Material) -> None:
    text = format_material_text(material)

    # Сначала отправляем текст
    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    # Потом файл, если он есть
    if material.file_id.strip():
        await application.bot.send_document(
            chat_id=chat_id,
            document=material.file_id.strip(),
            caption=f"{material.title}",
        )


# ----------------------------
# Игнор в группах (чтобы “не отвечал”)
# ----------------------------

async def ignore_non_command_messages_in_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if update.effective_message is None:
        return

    text = update.effective_message.text or ""

    # реагируем только на сообщения с #
    if "#" not in text:
        return

    results = db.search_materials(text, limit=5)

    if not results:
        return

    for material in results:
        await update.effective_message.reply_text(
            format_material_text(material),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


# ----------------------------
# Запуск
# ----------------------------

def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("register", register_group_command))
    application.add_handler(CommandHandler("bind_category", bind_category_command))
    application.add_handler(CommandHandler("deadline", deadline_command))
    application.add_handler(CommandHandler("deadlines", deadlines_command)) 

    # Кнопки меню
    application.add_handler(CallbackQueryHandler(menu_callback))

    # В личке: сначала обрабатываем обычный текст (без команд)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    # В личке: отдельно обрабатываем документы
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.ALL,
            file_router,
        )
    )

    # В группах: игнорировать все обычные сообщения
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            ignore_non_command_messages_in_groups,
        )
    )

    # Автоматическая проверка дедлайнов каждый час
    application.job_queue.run_repeating(
        lambda context: check_deadlines(context.application),
        interval=3600,
        first=60,
    )

    return application


from tornado.web import RequestHandler


class HealthHandler(RequestHandler):
    def get(self):
        self.write("OK")


def main() -> None:
    application = build_application()

    webhook_url = f"{RENDER_EXTERNAL_URL}/{WEBHOOK_PATH}"

    logger.info("Бот запускается через webhook")
    logger.info("PORT: %s", PORT)
    logger.info("Webhook URL: %s", webhook_url)

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
        drop_pending_updates=True,
        extra_routes=[(r"/health", HealthHandler)],
    )


if __name__ == "__main__":
    main()

