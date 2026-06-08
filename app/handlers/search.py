from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.handlers.materials import finalize_add_material
from app.keyboards import add_cancel_keyboard, main_menu_keyboard, material_view_keyboard
from app.services.materials_service import format_material_text, normalize_tags
from app.utils.chat import is_private_chat
from app.utils.context import get_db
from app.utils.favorites import is_favorite
from app.utils.security import require_admin
from app.utils.users import get_or_create_user_from_update


async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    db = get_db(context)
    is_admin = require_admin(update, db)
    results = db.search_materials(text, limit=10)
    user_id = get_or_create_user_from_update(db, update)
    if user_id is not None:
        db.log_search(user_id, text, len(results))

    if not results:
        await update.effective_message.reply_text(
            "Ничего не найдено.\n\nПопробуй:\n"
            "матан\n"
            "#экзамен\n"
            "интеграл"
        )
        return

    for material in results:
        favorite_state = (
            user_id is not None and is_favorite(db, user_id, material.material_id)
        )
        await update.effective_message.reply_text(
            format_material_text(material, db),
            parse_mode=ParseMode.HTML,
            reply_markup=material_view_keyboard(
                material.material_id,
                is_admin=is_admin,
                is_favorite=favorite_state,
                back_callback="MENU_MAIN",
                origin="MAIN",
            ),
            disable_web_page_preview=True,
        )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_user is None:
        return

    if not is_private_chat(update):
        return

    text = (update.effective_message.text or "").strip()
    if not text:
        return

    db = get_db(context)
    is_admin = require_admin(update, db)

    if context.user_data.get("awaiting_search_text") is True:
        context.user_data["awaiting_search_text"] = False
        await handle_search_text(update, context, text)
        return

    if not is_admin:
        await handle_search_text(update, context, text)
        return

    if context.user_data.get("awaiting_add_file") is True and text == "-":
        context.user_data["awaiting_add_file"] = False
        await finalize_add_material(update, context, file_id="")
        return

    if context.user_data.get("awaiting_add_title") is True:
        context.user_data["awaiting_add_title"] = False
        context.user_data["add_title"] = text
        await update.effective_message.reply_text(
            "Отлично. Теперь пришли описание (можно коротко, 1–5 строк).",
            reply_markup=add_cancel_keyboard(),
        )
        context.user_data["awaiting_add_description"] = True
        return

    if context.user_data.get("awaiting_add_description") is True:
        context.user_data["awaiting_add_description"] = False
        context.user_data["add_description"] = text
        await update.effective_message.reply_text(
            "Теперь пришли ссылку (если ссылки нет — напиши: - )",
            reply_markup=add_cancel_keyboard(),
        )
        context.user_data["awaiting_add_link"] = True
        return

    if context.user_data.get("awaiting_add_link") is True:
        context.user_data["awaiting_add_link"] = False
        link = text
        if link == "-":
            link = ""
        context.user_data["add_link"] = link
        await update.effective_message.reply_text(
            "Теперь теги (через пробел или запятую). Например: матан, экзамен, интеграл",
            reply_markup=add_cancel_keyboard(),
        )
        context.user_data["awaiting_add_tags"] = True
        return

    if context.user_data.get("awaiting_add_tags") is True:
        context.user_data["awaiting_add_tags"] = False
        context.user_data["add_tags"] = normalize_tags(text)
        await update.effective_message.reply_text(
            "Последний шаг: пришли файл (документом) или напиши: - (если без файла)",
            reply_markup=add_cancel_keyboard(),
        )
        context.user_data["awaiting_add_file"] = True
        return

    await update.effective_message.reply_text(
        "Я понимаю команды через кнопки. Открой меню:",
        reply_markup=main_menu_keyboard(is_admin=True),
    )
