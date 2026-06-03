from telegram import Update


def require_admin(update: Update, db) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return db.is_admin(user.id)


async def deny_if_not_admin(update: Update) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text("Доступ только для администратора.")
