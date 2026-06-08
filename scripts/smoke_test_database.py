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
from app.handlers.pepe import generate_pepe_response, split_telegram_reply
from app.personality.character_engine import generate_character_engine_context, get_character_engine
from app.personality.pickme_pepe import PepeMode, get_system_prompt
from app.services.analytics_service import AnalyticsService
from app.services.llm_service import (
    DEFAULT_OPENROUTER_MODEL,
    LLMProvider,
    LLMProviderNotConfiguredError,
    LLMRuntimeConfig,
    build_llm_request,
    generate_response,
    get_llm_adapter,
    normalize_provider,
    parse_openrouter_response,
)
from app.services.personality_service import build_pepe_context, generate_personality_context
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


def assert_pickme_pepe_prompts() -> None:
    for mode in PepeMode:
        prompt = get_system_prompt(mode)
        assert_true(isinstance(prompt, str) and prompt.strip(), f"Empty prompt for mode {mode.name}")
        assert_true(mode.name in prompt, f"Mode name missing in prompt for {mode.name}")


def assert_pickme_pepe_runtime_context() -> None:
    for mode in PepeMode:
        context = build_pepe_context(mode)
        assert_true(context.mode == mode, f"Invalid runtime mode for {mode.name}")
        assert_true(bool(context.system_prompt.strip()), f"Empty runtime prompt for {mode.name}")
        assert_true(bool(context.behavior_rules), f"Missing behavior rules for {mode.name}")
        assert_true(bool(context.style_examples), f"Missing style examples for {mode.name}")

        payload = generate_personality_context(mode)
        assert_true(payload["mode"] == mode.value, f"Invalid payload mode for {mode.name}")
        assert_true(bool(payload["system_prompt"]), f"Empty payload prompt for {mode.name}")
        assert_true(bool(payload["behavior_rules"]), f"Missing payload rules for {mode.name}")
        assert_true(bool(payload["style_examples"]), f"Missing payload examples for {mode.name}")


def assert_pickme_pepe_character_engine() -> None:
    engine = get_character_engine()
    assert_true(bool(engine.tone_variants), "Missing tone variants")
    assert_true(bool(engine.sarcasm_variants), "Missing sarcasm variants")
    assert_true(bool(engine.jab_variants), "Missing jab variants")
    assert_true(bool(engine.anti_npc_rules), "Missing anti-NPC rules")

    context = generate_character_engine_context()
    assert_true(bool(context["tone_variants"]), "Missing tone variants context")
    assert_true(bool(context["sarcasm_variants"]), "Missing sarcasm variants context")
    assert_true(bool(context["jab_variants"]), "Missing jab variants context")
    assert_true(bool(context["anti_npc_rules"]), "Missing anti-NPC rules context")


def assert_llm_adapter_foundation() -> None:
    pepe_context = build_pepe_context(PepeMode.SOFT)
    character_context = generate_character_engine_context()
    request = build_llm_request(
        user_message="Пепе, помоги с дедлайном",
        pepe_context=pepe_context,
        character_engine_context=character_context,
    )
    assert_true(request.user_message == "Пепе, помоги с дедлайном", "Invalid LLM request message")
    assert_true(request.pepe_context.mode == PepeMode.SOFT, "Invalid LLM request Pepe context")
    assert_true(bool(request.character_engine_context), "Missing LLM request character context")
    assert_true(normalize_provider("stub") == LLMProvider.STUB, "LLM provider normalization failed")
    assert_true(get_llm_adapter("openai").provider == LLMProvider.OPENAI, "Missing OpenAI adapter placeholder")
    openrouter_config = LLMRuntimeConfig(
        openrouter_api_key="smoke-openrouter-key",
        openrouter_model="smoke-openrouter-model",
    )
    assert_true(
        get_llm_adapter("openrouter", runtime_config=openrouter_config).provider == LLMProvider.OPENROUTER,
        "Missing OpenRouter adapter placeholder",
    )
    default_model_config = LLMRuntimeConfig(
        openrouter_api_key="smoke-openrouter-key",
        openrouter_model="",
    )
    default_model_adapter = get_llm_adapter("openrouter", runtime_config=default_model_config)
    assert_true(default_model_adapter.provider == LLMProvider.OPENROUTER, "OpenRouter default model failed")
    assert_true(default_model_adapter.model == DEFAULT_OPENROUTER_MODEL, "Invalid OpenRouter default model")
    assert_true(
        get_llm_adapter("openrouter").provider == LLMProvider.STUB,
        "OpenRouter adapter must fallback to STUB without API key",
    )
    assert_true(get_llm_adapter("local").provider == LLMProvider.LOCAL, "Missing local LLM adapter placeholder")

    response = generate_response(
        user_message=request.user_message,
        pepe_context=request.pepe_context,
        character_engine_context=request.character_engine_context,
    )
    assert_true(response.provider == LLMProvider.STUB, "Invalid stub LLM provider")
    assert_true(response.is_generated is False, "Stub LLM response must not be marked generated")
    assert_true(bool(response.text.strip()), "Empty stub LLM response")
    openrouter_fallback_response = generate_response(
        user_message=request.user_message,
        pepe_context=request.pepe_context,
        character_engine_context=request.character_engine_context,
        provider=LLMProvider.OPENROUTER,
    )
    assert_true(openrouter_fallback_response.provider == LLMProvider.STUB, "OpenRouter fallback failed")
    assert_true(
        openrouter_fallback_response.is_generated is False,
        "OpenRouter fallback must not be marked generated",
    )

    try:
        get_llm_adapter(LLMProvider.OPENAI).generate_response(request)
    except LLMProviderNotConfiguredError:
        pass
    else:
        raise AssertionError("OpenAI adapter must stay disconnected at this stage")


def assert_pepe_command_stub_foundation() -> None:
    response = generate_pepe_response("smoke pepe command")
    assert_true(response.provider == LLMProvider.STUB, "Invalid /pepe fallback provider")
    assert_true(bool(response.text.strip()), "Empty /pepe stub response")
    assert_true("LLM provider is not connected yet" in response.text, "Invalid /pepe stub provider response")

    chunks = split_telegram_reply("x" * 4101, max_length=4000)
    assert_true(len(chunks) == 2, "Long /pepe reply must be split")
    assert_true(all(len(chunk) <= 4000 for chunk in chunks), "Split /pepe reply chunk is too long")


def assert_openrouter_response_parser() -> None:
    parsed_text = parse_openrouter_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "Smoke OpenRouter response",
                    },
                }
            ]
        }
    )
    assert_true(parsed_text == "Smoke OpenRouter response", "OpenRouter parser failed")


def main() -> int:
    load_dotenv()

    smoke_telegram_id = int(os.getenv("SMOKE_TEST_TELEGRAM_ID", "900000001"))
    user_id: int | None = None
    material_id: int | None = None

    try:
        assert_pickme_pepe_prompts()
        assert_pickme_pepe_runtime_context()
        assert_pickme_pepe_character_engine()
        assert_llm_adapter_foundation()
        assert_pepe_command_stub_foundation()
        assert_openrouter_response_parser()

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
        analytics = AnalyticsService(db)
        searches_before = analytics.get_search_count()
        views_before = analytics.get_views_count()

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
        assert_true(
            analytics.get_search_count() >= searches_before + 1,
            "get_search_count failed",
        )
        top_queries = analytics.get_top_search_queries(limit=10000)
        assert_true(
            any(item.query == "smoke test query" and item.search_count > 0 for item in top_queries),
            "get_top_search_queries failed",
        )

        log_material_view(db, user_id, material_id)
        material_views = get_user_material_views(db, user_id, limit=10)
        assert_true(
            contains_material_view(material_views, material_id),
            "get_user_material_views failed",
        )
        assert_true(
            analytics.get_views_count() >= views_before + 1,
            "get_views_count failed",
        )
        recent_views = analytics.get_recent_views(limit=10000)
        assert_true(
            contains_material_view(recent_views, material_id),
            "get_recent_views failed",
        )

        popular_materials = get_popular_materials(db, limit=10000)
        assert_true(
            contains_popular_material(popular_materials, material_id),
            "get_popular_materials failed",
        )
        most_viewed_materials = analytics.get_most_viewed_materials(limit=10000)
        assert_true(
            contains_popular_material(most_viewed_materials, material_id),
            "get_most_viewed_materials failed",
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
