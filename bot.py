import asyncio
import logging
import os
import re
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

            # Добавим админа (тебя)
            cursor.execute(
                "INSERT OR IGNORE INTO admins(user_id) VALUES (?)",
                (ADMIN_USER_ID,),
            )

            # Если категорий нет — создадим стартовые
            cursor.execute("SELECT COUNT(*) AS c FROM categories")
            count = int(cursor.fetchone()["c"])
            if count == 0:
                starter_categories = [
                    ("Лекции", "📖", 1),
                    ("Практика", "🧪", 2),
                    ("Домашки", "📝", 3),
                    ("Ссылки", "🔗", 4),
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
        # Простой поиск по title/description/tags; SQLite LIKE
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

    lines = [
        f"<b>{safe_title}</b>",
        "",
        f"{safe_desc}",
        "",
        f"<b>Ссылка:</b> {safe_link}",
        f"<b>Теги:</b> {safe_tags}",
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

def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📚 Библиотека", callback_data="MENU_LIBRARY")],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="MENU_SEARCH")],
        [InlineKeyboardButton(text="➕ Добавить материал", callback_data="MENU_ADD")],
    ]
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
    for material in materials[:30]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=material.title[:45],
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


def material_view_keyboard(material_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📣 Отправить в группу", callback_data=f"SEND_{material_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="BACK_FROM_MATERIAL")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="MENU_MAIN")],
    ]
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

    if not require_admin(update):
        await deny_if_not_admin(update)
        return

    await update.effective_message.reply_text(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
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

    if not require_admin(update):
        await query.edit_message_text("Доступ только для администратора.")
        return

    data = query.data or ""

    if data == "MENU_MAIN":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())
        return

    if data == "MENU_LIBRARY":
        await query.edit_message_text("Выбери вкладку/категорию:", reply_markup=categories_keyboard())
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
        # Старт мастера добавления
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
            await query.edit_message_text("Категория не найдена.", reply_markup=categories_keyboard())
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
            await query.edit_message_text("Материал не найден.", reply_markup=back_to_main_keyboard())
            return

        # Запомним откуда пришли, чтобы кнопка “назад” работала
        context.user_data["last_material_category_id"] = material.category_id

        await query.edit_message_text(
            format_material_text(material),
            parse_mode=ParseMode.HTML,
            reply_markup=material_view_keyboard(material.material_id),
            disable_web_page_preview=True,
        )
        return

    if data == "BACK_FROM_MATERIAL":
        category_id = int(context.user_data.get("last_material_category_id", 0))
        if category_id <= 0:
            await query.edit_message_text("Выбери категорию:", reply_markup=categories_keyboard())
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
        material_id = int(data.replace("SEND_", "").strip())
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text("Материал не найден.", reply_markup=back_to_main_keyboard())
            return

        await query.edit_message_text(
            "Куда отправляем? Выбери группу:",
            reply_markup=groups_keyboard(material_id),
        )
        return

    if data.startswith("SENDTO_"):
        # SENDTO_{material_id}_{chat_id}
        parts = data.split("_", 2)
        if len(parts) != 3:
            await query.edit_message_text("Некорректная кнопка.", reply_markup=back_to_main_keyboard())
            return

        material_id = int(parts[1])
        chat_id = int(parts[2])

        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text("Материал не найден.", reply_markup=back_to_main_keyboard())
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
                reply_markup=material_view_keyboard(material_id),
            )
            return

        await query.edit_message_text(
            "Отправлено ✅",
            reply_markup=material_view_keyboard(material_id),
        )
        return

    if data.startswith("ADD_PICKCAT_"):
        category_id = int(data.replace("ADD_PICKCAT_", "").strip())
        category = db.get_category(category_id)
        if category is None:
            await query.edit_message_text("Категория не найдена.", reply_markup=categories_keyboard())
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
        # Просто заглушка
        return


# ----------------------------
# Добавление материала: текстовые шаги
# ----------------------------

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Все текстовые ответы от админа в личке — сюда
    if update.effective_message is None or update.effective_user is None:
        return

    if not is_private_chat(update):
        return

    if not require_admin(update):
        return

    text = (update.effective_message.text or "").strip()
    if not text:
        return

    # Поиск
    if context.user_data.get("awaiting_search_text") is True:
        context.user_data["awaiting_search_text"] = False
        await handle_search_text(update, context, text)
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

    # Если человек пишет что-то вне сценария — просто покажем меню
    await update.effective_message.reply_text(
        "Я понимаю команды через кнопки. Открой меню:",
        reply_markup=main_menu_keyboard(),
    )


async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    # Разберём запрос: слова + теги
    query = text.strip()
    # Если человек ввёл несколько токенов, можно искать целиком; это MVP
    results = db.search_materials(query=query, limit=20)

    if not results:
        await update.effective_message.reply_text(
            "Ничего не нашёл. Попробуй другие слова или #теги.",
            reply_markup=back_to_main_keyboard(),
        )
        return

    keyboard: List[List[InlineKeyboardButton]] = []
    for material in results:
        keyboard.append(
            [InlineKeyboardButton(text=material.title[:45], callback_data=f"MATERIAL_{material.material_id}")]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="MENU_MAIN")])

    await update.effective_message.reply_text(
        f"Нашёл материалов: {len(results)}. Выбери:",
        reply_markup=InlineKeyboardMarkup(keyboard),
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

    # Разрешим “-” текстом (без файла)
    if message.text is not None and message.text.strip() == "-":
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id="")
        return

    # Документом
    if message.document is not None:
        file_id = message.document.file_id
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id=file_id)
        return

    # Если прислали не документ
    await update.effective_message.reply_text(
        "Нужен именно файл-документ (как документ), или напиши '-' чтобы добавить без файла."
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

    await update.effective_message.reply_text(
        f"Сохранено ✅ (ID: {material_id})",
        reply_markup=main_menu_keyboard(),
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
    # Просто ничего не делаем — хендлер нужен, чтобы не было случайной логики
    return


# ----------------------------
# Запуск
# ----------------------------

def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("register", register_group_command))

    # Кнопки меню
    application.add_handler(CallbackQueryHandler(menu_callback))

    # В личке: приём файлов (документов) для добавления
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.Document.ALL | filters.TEXT),
            file_router,
        )
    )

    # В личке: приём текста (поиск, шаги мастера)
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, text_router)
    )

    # В группах: не отвечать
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, ignore_non_command_messages_in_groups)
    )

    return application


def main() -> None:
    application = build_application()
    logger.info("Бот запущен.")
    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
