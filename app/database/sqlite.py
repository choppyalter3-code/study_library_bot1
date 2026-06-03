import os
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

from app.database.base import STARTER_CATEGORIES, row_to_category, row_to_material
from app.models import Category, Material
from app.services.deadlines_service import parse_deadline_date


class SQLiteDatabase:
    backend_name = "sqlite"

    def __init__(self, database_path: str, admin_user_id: int) -> None:
        self.database_path = database_path
        self.admin_user_id = admin_user_id
        database_dir = os.path.dirname(os.path.abspath(self.database_path))
        if database_dir:
            os.makedirs(database_dir, exist_ok=True)
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    def _column_exists(self, cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return any(str(row["name"]) == column_name for row in cursor.fetchall())

    def _run_migrations(self, cursor: sqlite3.Cursor) -> None:
        if not self._column_exists(cursor, "deadlines", "reminded_at"):
            cursor.execute("ALTER TABLE deadlines ADD COLUMN reminded_at TEXT")

        cursor.execute(
            """
            DELETE FROM destinations
            WHERE destination_id NOT IN (
                SELECT MAX(destination_id)
                FROM destinations
                GROUP BY category_id
            )
            """
        )

        cursor.execute("SELECT deadline_id, deadline_date FROM deadlines")
        for row in cursor.fetchall():
            old_value = str(row["deadline_date"])
            normalized = parse_deadline_date(old_value)
            if normalized and normalized != old_value:
                cursor.execute(
                    "UPDATE deadlines SET deadline_date = ? WHERE deadline_id = ?",
                    (normalized, int(row["deadline_id"])),
                )

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
        index_statements = [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name_unique ON categories(name)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_destinations_category_unique ON destinations(category_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_id_unique ON users(telegram_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_favorites_unique ON favorites(user_id, material_id)",
            "CREATE INDEX IF NOT EXISTS idx_materials_category_id ON materials(category_id)",
            "CREATE INDEX IF NOT EXISTS idx_materials_title ON materials(title)",
            "CREATE INDEX IF NOT EXISTS idx_materials_description ON materials(description)",
            "CREATE INDEX IF NOT EXISTS idx_materials_tags ON materials(tags)",
            "CREATE INDEX IF NOT EXISTS idx_deadlines_date ON deadlines(deadline_date)",
            "CREATE INDEX IF NOT EXISTS idx_deadlines_reminded_at ON deadlines(reminded_at)",
            "CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_favorites_material_id ON favorites(material_id)",
            "CREATE INDEX IF NOT EXISTS idx_material_views_user_id ON material_views(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_material_views_material_id ON material_views(material_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_logs_user_id ON search_logs(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_search_logs_query ON search_logs(query)",
        ]
        for statement in index_statements:
            cursor.execute(statement)

    def _init_database(self) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS groups (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS categories (
                    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    icon TEXT NOT NULL,
                    sort_order INTEGER NOT NULL
                );
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
                );
                CREATE TABLE IF NOT EXISTS destinations (
                    destination_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    FOREIGN KEY (category_id) REFERENCES categories(category_id)
                );
                CREATE TABLE IF NOT EXISTS deadlines (
                    deadline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    deadline_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reminded_at TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (material_id) REFERENCES materials(material_id)
                );
                CREATE TABLE IF NOT EXISTS material_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    viewed_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (material_id) REFERENCES materials(material_id)
                );
                CREATE TABLE IF NOT EXISTS search_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    results_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                """
            )
            self._run_migrations(cursor)
            self._create_indexes(cursor)
            cursor.execute(
                "INSERT OR IGNORE INTO admins(user_id) VALUES (?)",
                (self.admin_user_id,),
            )
            cursor.execute("SELECT COUNT(*) AS c FROM categories")
            if int(cursor.fetchone()["c"]) == 0:
                cursor.executemany(
                    "INSERT INTO categories(name, icon, sort_order) VALUES (?, ?, ?)",
                    STARTER_CATEGORIES,
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
            cursor.execute("SELECT chat_id, title FROM groups ORDER BY registered_at DESC")
            return [(int(row["chat_id"]), str(row["title"])) for row in cursor.fetchall()]
        finally:
            connection.close()

    def upsert_destination(self, category_id: int, chat_id: int, thread_id: int, title: str) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO destinations(category_id, chat_id, thread_id, title)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    thread_id = excluded.thread_id,
                    title = excluded.title
                """,
                (category_id, chat_id, thread_id, title),
            )
            connection.commit()
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
            return [row_to_category(row) for row in cursor.fetchall()]
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
            return row_to_category(row) if row else None
        finally:
            connection.close()

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
            return row_to_category(row) if row else None
        finally:
            connection.close()

    def add_material(self, category_id: int, title: str, description: str, link: str, tags: str, file_id: str) -> int:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO materials(category_id, title, description, link, tags, file_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (category_id, title, description, link, tags, file_id, datetime.utcnow().isoformat()),
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
            return [row_to_material(row) for row in cursor.fetchall()]
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
            return row_to_material(row) if row else None
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
            return [row_to_material(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def add_deadline(self, text: str, deadline_date: str) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO deadlines(text, deadline_date, created_at, reminded_at)
                VALUES (?, ?, ?, NULL)
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
                SELECT deadline_id, text, deadline_date, reminded_at
                FROM deadlines
                ORDER BY deadline_date ASC
                """
            )
            return cursor.fetchall()
        finally:
            connection.close()

    def mark_deadline_reminded(self, deadline_id: int) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE deadlines SET reminded_at = ? WHERE deadline_id = ?",
                (datetime.utcnow().isoformat(), deadline_id),
            )
            connection.commit()
        finally:
            connection.close()

    def get_or_create_user(self, telegram_id: int, username: str, full_name: str, role: str = "student") -> int:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            now = datetime.utcnow().isoformat()
            cursor.execute(
                """
                INSERT INTO users(telegram_id, username, full_name, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    role = excluded.role,
                    username = excluded.username,
                    full_name = excluded.full_name,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, username, full_name, role, now, now),
            )
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_id = int(cursor.fetchone()["id"])
            connection.commit()
            return user_id
        finally:
            connection.close()

    def add_favorite(self, user_id: int, material_id: int) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO favorites(user_id, material_id, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, material_id, datetime.utcnow().isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def remove_favorite(self, user_id: int, material_id: int) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM favorites WHERE user_id = ? AND material_id = ?",
                (user_id, material_id),
            )
            connection.commit()
        finally:
            connection.close()

    def list_favorites(self, user_id: int) -> List[Material]:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.material_id, m.category_id, m.title, m.description, m.link, m.tags, m.file_id, m.created_at
                FROM favorites f
                JOIN materials m ON m.material_id = f.material_id
                WHERE f.user_id = ?
                ORDER BY f.created_at DESC
                """,
                (user_id,),
            )
            return [row_to_material(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def log_material_view(self, user_id: int, material_id: int) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO material_views(user_id, material_id, viewed_at)
                VALUES (?, ?, ?)
                """,
                (user_id, material_id, datetime.utcnow().isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def log_search(self, user_id: int, query: str, results_count: int) -> None:
        connection = self._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO search_logs(user_id, query, results_count, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, query, results_count, datetime.utcnow().isoformat()),
            )
            connection.commit()
        finally:
            connection.close()
