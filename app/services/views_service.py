from typing import List

from app.database.base import BaseDatabase
from app.models import MaterialView, PopularMaterial


def log_material_view(db: BaseDatabase, user_id: int, material_id: int) -> None:
    db.log_material_view(user_id, material_id)


def get_user_material_views(
    db: BaseDatabase,
    user_id: int,
    limit: int = 20,
) -> List[MaterialView]:
    return db.list_material_views(user_id, limit=limit)


def get_popular_materials(
    db: BaseDatabase,
    limit: int = 10,
) -> List[PopularMaterial]:
    return db.list_popular_materials(limit=limit)
