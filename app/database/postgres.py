from datetime import datetime
from typing import List, Optional, Tuple

from app.database.base import (
    STARTER_CATEGORIES,
    row_to_category,
    row_to_material,
    row_to_material_view,
    row_to_popular_material,
    row_to_search_log,
)
from app.models import Category, Material, MaterialView, PopularMaterial, SearchLog
from app.services.deadlines_service import parse_deadline_date


class PostgresDatabase:
    backend_name = "postgres"

    def __init__(self, database_url: str, admin_user_id: int) -> None:
        self.database_url = database_url
        self.admin_user_id = admin_user_id
        self._init_database()

    def _get_connection(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _init_database(self) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                for statement in self._schema_statements():
                    cursor.execute(statement)
                self._run_migrations(cursor)
                self._create_indexes(cursor)
                cursor.execute(
                    "INSERT INTO admins(user_id) VALUES (%s) ON CONFLICT(user_id) DO NOTHING",
                    (self.admin_user_id,),
                )
                cursor.execute("SELECT COUNT(*) AS c FROM categories")
                if int(cursor.fetchone()["c"]) == 0:
                    cursor.executemany(
                        "INSERT INTO categories(name, icon, sort_order) VALUES (%s, %s, %s)",
                        STARTER_CATEGORIES,
                    )
            connection.commit()

    def _schema_statements(self) -> list[str]:
        return [
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT NOT NULL,
                registered_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS categories (
                category_id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT NOT NULL,
                sort_order INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS materials (
                material_id BIGSERIAL PRIMARY KEY,
                category_id BIGINT NOT NULL REFERENCES categories(category_id),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                link TEXT NOT NULL,
                tags TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS destinations (
                destination_id BIGSERIAL PRIMARY KEY,
                category_id BIGINT NOT NULL REFERENCES categories(category_id),
                chat_id BIGINT NOT NULL,
                thread_id BIGINT NOT NULL,
                title TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS deadlines (
                deadline_id BIGSERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                deadline_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reminded_at TEXT
            )
            """,
            "ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS reminded_at TEXT",
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS favorites (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                material_id BIGINT NOT NULL REFERENCES materials(material_id),
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS material_views (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                material_id BIGINT NOT NULL REFERENCES materials(material_id),
                viewed_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS search_logs (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                query TEXT NOT NULL,
                results_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
        ]

    def _run_migrations(self, cursor) -> None:
        cursor.execute(
            """
            DELETE FROM destinations d
            WHERE d.destination_id NOT IN (
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
                    "UPDATE deadlines SET deadline_date = %s WHERE deadline_id = %s",
                    (normalized, int(row["deadline_id"])),
                )

    def _create_indexes(self, cursor) -> None:
        index_statements = [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_name_unique ON categories(lower(name))",
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

    def is_admin(self, user_id: int) -> bool:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM admins WHERE user_id = %s", (user_id,))
                return cursor.fetchone() is not None

    def upsert_group(self, chat_id: int, title: str) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO groups(chat_id, title, registered_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title
                    """,
                    (chat_id, title, datetime.utcnow().isoformat()),
                )
            connection.commit()

    def list_groups(self) -> List[Tuple[int, str]]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT chat_id, title FROM groups ORDER BY registered_at DESC")
                return [(int(row["chat_id"]), str(row["title"])) for row in cursor.fetchall()]

    def upsert_destination(self, category_id: int, chat_id: int, thread_id: int, title: str) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO destinations(category_id, chat_id, thread_id, title)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(category_id) DO UPDATE SET
                        chat_id = excluded.chat_id,
                        thread_id = excluded.thread_id,
                        title = excluded.title
                    """,
                    (category_id, chat_id, thread_id, title),
                )
            connection.commit()

    def get_destination_for_category(self, category_id: int):
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT chat_id, thread_id
                    FROM destinations
                    WHERE category_id = %s
                    LIMIT 1
                    """,
                    (category_id,),
                )
                row = cursor.fetchone()
                if row:
                    return int(row["chat_id"]), int(row["thread_id"])
                return None

    def list_categories(self) -> List[Category]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT category_id, name, icon, sort_order FROM categories ORDER BY sort_order ASC, name ASC"
                )
                return [row_to_category(row) for row in cursor.fetchall()]

    def get_category(self, category_id: int) -> Optional[Category]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT category_id, name, icon, sort_order FROM categories WHERE category_id = %s",
                    (category_id,),
                )
                row = cursor.fetchone()
                return row_to_category(row) if row else None

    def get_category_by_name(self, category_name: str) -> Optional[Category]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category_id, name, icon, sort_order
                    FROM categories
                    WHERE lower(name) = lower(%s)
                    LIMIT 1
                    """,
                    (category_name.strip(),),
                )
                row = cursor.fetchone()
                return row_to_category(row) if row else None

    def add_material(self, category_id: int, title: str, description: str, link: str, tags: str, file_id: str) -> int:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO materials(category_id, title, description, link, tags, file_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING material_id
                    """,
                    (category_id, title, description, link, tags, file_id, datetime.utcnow().isoformat()),
                )
                material_id = int(cursor.fetchone()["material_id"])
            connection.commit()
            return material_id

    def list_materials_by_category(self, category_id: int) -> List[Material]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                    FROM materials
                    WHERE category_id = %s
                    ORDER BY material_id DESC
                    """,
                    (category_id,),
                )
                return [row_to_material(row) for row in cursor.fetchall()]

    def get_material(self, material_id: int) -> Optional[Material]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                    FROM materials
                    WHERE material_id = %s
                    """,
                    (material_id,),
                )
                row = cursor.fetchone()
                return row_to_material(row) if row else None

    def search_materials(self, query: str, limit: int = 20) -> List[Material]:
        q = f"%{query.strip().lower()}%"
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT material_id, category_id, title, description, link, tags, file_id, created_at
                    FROM materials
                    WHERE lower(title) LIKE %s
                       OR lower(description) LIKE %s
                       OR lower(tags) LIKE %s
                    ORDER BY material_id DESC
                    LIMIT %s
                    """,
                    (q, q, q, limit),
                )
                return [row_to_material(row) for row in cursor.fetchall()]

    def add_deadline(self, text: str, deadline_date: str) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO deadlines(text, deadline_date, created_at, reminded_at)
                    VALUES (%s, %s, %s, NULL)
                    """,
                    (text, deadline_date, datetime.utcnow().isoformat()),
                )
            connection.commit()

    def list_deadlines(self):
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT deadline_id, text, deadline_date, reminded_at
                    FROM deadlines
                    ORDER BY deadline_date ASC
                    """
                )
                return cursor.fetchall()

    def mark_deadline_reminded(self, deadline_id: int) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE deadlines SET reminded_at = %s WHERE deadline_id = %s",
                    (datetime.utcnow().isoformat(), deadline_id),
                )
            connection.commit()

    def get_or_create_user(self, telegram_id: int, username: str, full_name: str, role: str = "student") -> int:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                now = datetime.utcnow().isoformat()
                cursor.execute(
                    """
                    INSERT INTO users(telegram_id, username, full_name, role, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        role = excluded.role,
                        username = excluded.username,
                        full_name = excluded.full_name,
                        is_active = TRUE,
                        updated_at = excluded.updated_at
                    RETURNING id
                    """,
                    (telegram_id, username, full_name, role, now, now),
                )
                user_id = int(cursor.fetchone()["id"])
            connection.commit()
            return user_id

    def add_favorite(self, user_id: int, material_id: int) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO favorites(user_id, material_id, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(user_id, material_id) DO NOTHING
                    """,
                    (user_id, material_id, datetime.utcnow().isoformat()),
                )
            connection.commit()

    def remove_favorite(self, user_id: int, material_id: int) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM favorites WHERE user_id = %s AND material_id = %s",
                    (user_id, material_id),
                )
            connection.commit()

    def list_favorites(self, user_id: int) -> List[Material]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.material_id, m.category_id, m.title, m.description, m.link, m.tags, m.file_id, m.created_at
                    FROM favorites f
                    JOIN materials m ON m.material_id = f.material_id
                    WHERE f.user_id = %s
                    ORDER BY f.created_at DESC
                    """,
                    (user_id,),
                )
                return [row_to_material(row) for row in cursor.fetchall()]

    def log_material_view(self, user_id: int, material_id: int) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO material_views(user_id, material_id, viewed_at)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, material_id, datetime.utcnow().isoformat()),
                )
            connection.commit()

    def log_search(self, user_id: int, query: str, results_count: int) -> None:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO search_logs(user_id, query, results_count, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, query, results_count, datetime.utcnow().isoformat()),
                )
            connection.commit()

    def list_material_views(self, user_id: int, limit: int = 20) -> List[MaterialView]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.material_id, m.category_id, m.title, m.description, m.link, m.tags, m.file_id, m.created_at,
                           mv.viewed_at
                    FROM material_views mv
                    JOIN materials m ON m.material_id = mv.material_id
                    WHERE mv.user_id = %s
                    ORDER BY mv.viewed_at DESC, mv.id DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return [row_to_material_view(row) for row in cursor.fetchall()]

    def list_recent_searches(self, user_id: int, limit: int = 10) -> List[SearchLog]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT query, results_count, created_at
                    FROM search_logs
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                return [row_to_search_log(row) for row in cursor.fetchall()]

    def list_popular_materials(self, limit: int = 10) -> List[PopularMaterial]:
        with self._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.material_id, m.category_id, m.title, m.description, m.link, m.tags, m.file_id, m.created_at,
                           COUNT(mv.id) AS views_count
                    FROM material_views mv
                    JOIN materials m ON m.material_id = mv.material_id
                    GROUP BY m.material_id, m.category_id, m.title, m.description, m.link, m.tags, m.file_id, m.created_at
                    ORDER BY views_count DESC, MAX(mv.viewed_at) DESC, m.material_id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [row_to_popular_material(row) for row in cursor.fetchall()]
