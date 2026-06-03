import logging

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.keyboards import add_cancel_keyboard, main_menu_keyboard
from app.services.materials_service import format_material_text
from app.services.telegram_service import send_material_to_chat
from app.utils.chat import is_private_chat
from app.utils.context import get_db
from app.utils.security import require_admin
from app.utils.state import clear_add_state


logger = logging.getLogger("study_library_bot")


async def file_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_message is None or update.effective_user is None:
        return

    if not is_private_chat(update):
        return

    if not require_admin(update, db):
        return

    if context.user_data.get("awaiting_add_file") is not True:
        return

    message: Message = update.effective_message
    if message.document is not None:
        file_id = message.document.file_id
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id=file_id)
        return

    await update.effective_message.reply_text(
        "Нужен файл как документ, или напиши '-' чтобы добавить без файла.",
        reply_markup=add_cancel_keyboard(),
    )


async def finalize_add_material(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str) -> None:
    db = get_db(context)
    category_id = int(context.user_data.get("add_category_id", 0))
    title = str(context.user_data.get("add_title", "")).strip()
    description = str(context.user_data.get("add_description", "")).strip()
    link = str(context.user_data.get("add_link", "")).strip()
    tags = str(context.user_data.get("add_tags", "")).strip()

    if not link:
        link = "—"

    if category_id <= 0 or not title or not description or not tags:
        clear_add_state(context)
        await update.effective_message.reply_text(
            "Не хватает данных для сохранения. Давай начнём заново: /start"
        )
        return

    material_id = db.add_material(
        category_id=category_id,
        title=title,
        description=description,
        link=link,
        tags=tags,
        file_id=file_id or "",
    )

    destination = db.get_destination_for_category(category_id)
    if destination:
        chat_id, thread_id = destination
        try:
            material = db.get_material(material_id)
            if material is not None:
                await send_material_to_chat(
                    application=context.application,
                    chat_id=chat_id,
                    material=material,
                    db=db,
                    thread_id=thread_id,
                )
        except Exception as error:
            logger.error("Ошибка автоотправки: %s", error)

    clear_add_state(context)
    await update.effective_message.reply_text(
        f"Сохранено ✅ (ID: {material_id})",
        reply_markup=main_menu_keyboard(is_admin=True),
    )


async def ignore_non_command_messages_in_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if update.effective_message is None:
        return

    text = update.effective_message.text or ""
    if "#" not in text:
        return

    results = db.search_materials(text, limit=5)
    if not results:
        return

    for material in results:
        await update.effective_message.reply_text(
            format_material_text(material, db),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
