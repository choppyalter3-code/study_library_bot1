from typing import List

from app.database.base import BaseDatabase
from app.models import MaterialView, PopularMaterial, SearchQueryStat


TELEGRAM_MESSAGE_LIMIT = 4096
STAT_ITEM_TEXT_LIMIT = 80
TRUNCATION_SUFFIX = "..."


def _truncate_text(text: str, limit: int = STAT_ITEM_TEXT_LIMIT) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized

    return normalized[: limit - len(TRUNCATION_SUFFIX)].rstrip() + TRUNCATION_SUFFIX


def _truncate_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    if len(text) <= limit:
        return text

    return text[: limit - len(TRUNCATION_SUFFIX)].rstrip() + TRUNCATION_SUFFIX


class AnalyticsService:
    def __init__(self, db: BaseDatabase) -> None:
        self.db = db

    def get_most_viewed_materials(self, limit: int = 10) -> List[PopularMaterial]:
        return self.db.list_popular_materials(limit=limit)

    def get_recent_views(self, limit: int = 20) -> List[MaterialView]:
        return self.db.list_recent_material_views(limit=limit)

    def get_top_search_queries(self, limit: int = 20) -> List[SearchQueryStat]:
        return self.db.list_top_search_queries(limit=limit)

    def get_search_count(self) -> int:
        return self.db.count_searches()

    def get_views_count(self) -> int:
        return self.db.count_material_views()


def format_admin_statistics(db: BaseDatabase) -> str:
    analytics = AnalyticsService(db)
    top_materials = analytics.get_most_viewed_materials(limit=10)
    top_queries = analytics.get_top_search_queries(limit=10)

    lines = [
        "📊 Статистика",
        "",
        f"👁 Просмотров: {analytics.get_views_count()}",
        f"🔎 Поисковых запросов: {analytics.get_search_count()}",
        "",
        "ТОП-10 материалов:",
    ]

    if top_materials:
        for index, item in enumerate(top_materials, start=1):
            title = _truncate_text(item.material.title or "Без названия")
            lines.append(f"{index}. {title} — {item.views_count}")
    else:
        lines.append("Пока нет просмотров.")

    lines.extend(["", "ТОП-10 поисковых запросов:"])

    if top_queries:
        for index, item in enumerate(top_queries, start=1):
            query = _truncate_text(item.query)
            lines.append(f"{index}. {query} — {item.search_count}")
    else:
        lines.append("Пока нет поисковых запросов.")

    return _truncate_message("\n".join(lines))
