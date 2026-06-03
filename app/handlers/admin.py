from telegram import Update
from telegram.ext import ContextTypes

from app.keyboards import main_menu_keyboard
from app.utils.chat import is_private_chat
from app.utils.context import get_db
from app.utils.security import require_admin
from app.utils.state import clear_interaction_state


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_message is None:
        return

    if not is_private_chat(update):
        return

    clear_interaction_state(context)
    is_admin = require_admin(update, db)

    await update.effective_message.reply_text(
        "Главное меню:",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_message is None:
        return

    if not is_private_chat(update):
        return

    clear_interaction_state(context)
    is_admin = require_admin(update, db)

    await update.effective_message.reply_text(
        "Действие отменено. Главное меню:",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


async def register_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_chat is None or update.effective_message is None:
        return

    if update.effective_chat.type == "private":
        await update.effective_message.reply_text("Эта команда нужна в группе.")
        return

    if not require_admin(update, db):
        return

    title = update.effective_chat.title or "Без названия"
    db.upsert_group(update.effective_chat.id, title)

    await update.effective_message.reply_text(
        f"Группа зарегистрирована: {title}\nТеперь можно отправлять сюда материалы из меню бота."
    )


async def bind_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_chat is None or update.effective_message is None:
        return

    if not require_admin(update, db):
        return

    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "Эту команду нужно писать в теме группы, а не в личке."
        )
        return

    if update.effective_message.message_thread_id is None:
        await update.effective_message.reply_text(
            "Эту команду нужно писать внутри конкретной темы форума."
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Использование: /bind_category Домашки"
        )
        return

    category_name = " ".join(context.args).strip()
    category = db.get_category_by_name(category_name)

    if category is None:
        await update.effective_message.reply_text(
            f"Категория '{category_name}' не найдена."
        )
        return

    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id
    topic_title = f"{category.name} → thread {thread_id}"

    db.upsert_destination(
        category_id=category.category_id,
        chat_id=chat_id,
        thread_id=thread_id,
        title=topic_title,
    )

    await update.effective_message.reply_text(
        f"Готово ✅\nКатегория '{category.name}' теперь привязана к этой теме."
    )
