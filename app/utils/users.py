from typing import Optional

from telegram import Update


def get_or_create_user_from_update(db, update: Update) -> Optional[int]:
    user = update.effective_user
    if user is None:
        return None

    username = user.username or ""
    full_name = user.full_name or ""
    role = "admin" if db.is_admin(user.id) else "student"
    return db.get_or_create_user(
        telegram_id=user.id,
        username=username,
        full_name=full_name,
        role=role,
    )
