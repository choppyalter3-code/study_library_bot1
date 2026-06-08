def is_favorite(db, user_id: int, material_id: int) -> bool:
    return any(material.material_id == material_id for material in db.list_favorites(user_id))
