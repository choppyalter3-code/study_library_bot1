from typing import List

from app.database.base import BaseDatabase
from app.models import SearchLog


def log_search_query(
    db: BaseDatabase,
    user_id: int,
    query: str,
    results_count: int,
) -> None:
    normalized_query = query.strip()
    if not normalized_query:
        return

    db.log_search(user_id, normalized_query, results_count)


def get_recent_search_queries(
    db: BaseDatabase,
    user_id: int,
    limit: int = 10,
) -> List[SearchLog]:
    return db.list_recent_searches(user_id, limit=limit)
