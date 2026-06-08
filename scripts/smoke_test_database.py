from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        return False

from app.config import load_config
from app.database import create_database
from app.services.search_history_service import get_recent_search_queries, log_search_query
from app.services.views_service import (
    get_popular_materials,
    get_user_material_views,
    log_material_view,
)


REQUIRED_TABLES = {
    "admins",
    "groups",
    "categories",
    "materials",
    "destinations",
    "deadlines",
    "users",
    "favorites",
    "material_views",
    "search_logs",
}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def fetch_table_names(db) -> set[str]:
    if db.backend_name == "sqlite":
        connection = db._get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type = ?", ("table",))
            return {str(row["name"]) for row in cursor.fetchall()}
        finally:
            connection.close()

    if db.backend_name == "postgres":
        with db._get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    """,
                    ("public",),
                )
                return {str(row["table_name"]) for row in cursor.fetchall()}

    raise RuntimeError(f"Unsupported database backend: {db.backend_name}")


def cleanup_smoke_rows(db, user_id: int | None, material_id: int | None, telegram_id: int) -> None:
    if user_id is None and material_id is None:
        return

    if db.backend_name == "sqlite":
        connection = db._get_connection()
        placeholder = "?"
    elif db.backend_name == "postgres":
        connection = db._get_connection()
        placeholder = "%s"
    else:
        return

    try:
        cursor = connection.cursor()
        if user_id is not None:
            cursor.execute(f"DELETE FROM search_logs WHERE user_id = {placeholder}", (user_id,))
            cursor.execute(f"DELETE FROM material_views WHERE user_id = {placeholder}", (user_id,))
            cursor.execute(f"DELETE FROM favorites WHERE user_id = {placeholder}", (user_id,))
        if material_id is not None:
            cursor.execute(f"DELETE FROM favorites WHERE material_id = {placeholder}", (material_id,))
            cursor.execute(f"DELETE FROM material_views WHERE material_id = {placeholder}", (material_id,))
            cursor.execute(f"DELETE FROM materials WHERE material_id = {placeholder}", (material_id,))
        cursor.execute(f"DELETE FROM users WHERE telegram_id = {placeholder}", (telegram_id,))
        connection.commit()
    finally:
        connection.close()


def contains_material(materials: Iterable, material_id: int) -> bool:
    return any(material.material_id == material_id for material in materials)


def count_material(materials: Iterable, material_id: int) -> int:
    return sum(1 for material in materials if material.material_id == material_id)


def contains_material_view(views: Iterable, material_id: int) -> bool:
    return any(view.material.material_id == material_id for view in views)


def contains_popular_material(materials: Iterable, material_id: int) -> bool:
    return any(item.material.material_id == material_id and item.views_count > 0 for item in materials)


def main() -> int:
    load_dotenv()

    smoke_telegram_id = int(os.getenv("SMOKE_TEST_TELEGRAM_ID", "900000001"))
    user_id: int | None = None
    material_id: int | None = None

    try:
        config = load_config()
        db = create_database(config)
        print(f"Database backend: {db.backend_name}")

        tables = fetch_table_names(db)
        missing_tables = REQUIRED_TABLES - tables
        assert_true(not missing_tables, f"Missing tables: {', '.join(sorted(missing_tables))}")

        user_id = db.get_or_create_user(
            telegram_id=smoke_telegram_id,
            username="smoke_test_user",
            full_name="Smoke Test User",
            role="student",
        )
        assert_true(isinstance(user_id, int) and user_id > 0, "get_or_create_user failed")

        categories = db.list_categories()
        assert_true(bool(categories), "No categories found after schema initialization")
        category_id = categories[0].category_id

        material_id = db.add_material(
            category_id=category_id,
            title="SMOKE TEST MATERIAL",
            description="Temporary material created by scripts/smoke_test_database.py",
            link="—",
            tags="#smoke_test",
            file_id="",
        )
        assert_true(isinstance(material_id, int) and material_id > 0, "add_material failed")

        db.add_favorite(user_id, material_id)
        db.add_favorite(user_id, material_id)
        favorites = db.list_favorites(user_id)
        assert_true(contains_material(favorites, material_id), "add_favorite/list_favorites failed")
        assert_true(
            count_material(favorites, material_id) == 1,
            "add_favorite created duplicate favorite",
        )

        db.remove_favorite(user_id, material_id)
        favorites_after_remove = db.list_favorites(user_id)
        assert_true(
            not contains_material(favorites_after_remove, material_id),
            "remove_favorite failed",
        )

        log_search_query(db, user_id, "smoke test query", 1)
        recent_searches = get_recent_search_queries(db, user_id, limit=10)
        assert_true(
            any(search.query == "smoke test query" and search.created_at_iso for search in recent_searches),
            "get_recent_search_queries failed",
        )

        log_material_view(db, user_id, material_id)
        material_views = get_user_material_views(db, user_id, limit=10)
        assert_true(
            contains_material_view(material_views, material_id),
            "get_user_material_views failed",
        )

        popular_materials = get_popular_materials(db, limit=100)
        assert_true(
            contains_popular_material(popular_materials, material_id),
            "get_popular_materials failed",
        )

        print("SUCCESS")
        return 0
    except Exception as error:
        print(f"ERROR: {error}")
        return 1
    finally:
        try:
            if "db" in locals():
                cleanup_smoke_rows(db, user_id, material_id, smoke_telegram_id)
        except Exception as cleanup_error:
            print(f"ERROR: cleanup failed: {cleanup_error}")


if __name__ == "__main__":
    raise SystemExit(main())
