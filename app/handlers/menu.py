from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.keyboards import (
    add_cancel_keyboard,
    back_to_main_keyboard,
    categories_keyboard,
    groups_keyboard,
    main_menu_keyboard,
    material_view_keyboard,
    materials_keyboard,
)
from app.services.materials_service import format_material_text
from app.services.telegram_service import send_material_to_chat
from app.utils.chat import is_private_chat
from app.utils.context import get_db
from app.utils.security import require_admin
from app.utils.state import clear_add_state, clear_interaction_state
from app.utils.users import get_or_create_user_from_update


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    if not is_private_chat(update):
        return

    db = get_db(context)
    is_admin = require_admin(update, db)
    data = query.data or ""

    if data == "MENU_MAIN":
        clear_interaction_state(context)
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return

    if data == "MENU_LIBRARY":
        clear_interaction_state(context)
        await query.edit_message_text(
            "Выбери вкладку/категорию:",
            reply_markup=categories_keyboard(db),
        )
        return

    if data == "MENU_SEARCH":
        clear_interaction_state(context)
        await query.edit_message_text(
            "Напиши запрос (слова или #теги). Например:\n"
            "матан\n"
            "#экзамен\n"
            "интеграл #матан",
            reply_markup=back_to_main_keyboard(),
        )
        context.user_data["awaiting_search_text"] = True
        return

    if data == "MENU_ADD":
        clear_interaction_state(context)
        if not is_admin:
            await query.answer(
                "Только администратор может добавлять материалы",
                show_alert=True,
            )
            return

        keyboard: List[List[InlineKeyboardButton]] = []
        for category in db.list_categories():
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"{category.icon} {category.name}",
                        callback_data=f"ADD_PICKCAT_{category.category_id}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="MENU_MAIN")])
        keyboard.append([InlineKeyboardButton(text="Отменить добавление", callback_data="ADD_CANCEL")])

        await query.edit_message_text(
            "Куда добавляем материал? Выбери категорию:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "ADD_CANCEL":
        clear_interaction_state(context)
        await query.edit_message_text(
            "Добавление отменено. Главное меню:",
            reply_markup=main_menu_keyboard(is_admin=is_admin),
        )
        return

    if data.startswith("CATEGORY_"):
        clear_interaction_state(context)
        category_id = int(data.replace("CATEGORY_", "").strip())
        category = db.get_category(category_id)
        if category is None:
            await query.edit_message_text(
                "Категория не найдена.",
                reply_markup=categories_keyboard(db),
            )
            return

        context.user_data["last_category_id"] = category_id
        await query.edit_message_text(
            f"{category.icon} {category.name}\nМатериалы:",
            reply_markup=materials_keyboard(db, category_id),
        )
        return

    if data.startswith("MATERIAL_"):
        clear_interaction_state(context)
        material_id = int(data.replace("MATERIAL_", "").strip())
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        user_id = get_or_create_user_from_update(db, update)
        if user_id is not None:
            db.log_material_view(user_id, material.material_id)
        context.user_data["last_material_category_id"] = material.category_id
        await query.edit_message_text(
            format_material_text(material, db),
            parse_mode=ParseMode.HTML,
            reply_markup=material_view_keyboard(material.material_id, is_admin=is_admin),
            disable_web_page_preview=True,
        )
        return

    if data == "BACK_FROM_MATERIAL":
        clear_interaction_state(context)
        category_id = int(context.user_data.get("last_material_category_id", 0))
        if category_id <= 0:
            await query.edit_message_text(
                "Выбери категорию:",
                reply_markup=categories_keyboard(db),
            )
            return

        category = db.get_category(category_id)
        name = category.name if category else "Категория"
        icon = category.icon if category else "📚"
        await query.edit_message_text(
            f"{icon} {name}\nМатериалы:",
            reply_markup=materials_keyboard(db, category_id),
        )
        return

    if data.startswith("SEND_"):
        if not is_admin:
            await query.answer(
                "Только администратор может отправлять материалы в группу",
                show_alert=True,
            )
            return

        material_id = int(data.replace("SEND_", "").strip())
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        await query.edit_message_text(
            "Куда отправляем? Выбери группу:",
            reply_markup=groups_keyboard(db, material_id),
        )
        return

    if data.startswith("SENDTO_"):
        if not is_admin:
            await query.answer(
                "Только администратор может отправлять материалы в группу",
                show_alert=True,
            )
            return

        parts = data.split("_", 2)
        if len(parts) != 3:
            await query.edit_message_text(
                "Некорректная кнопка.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        material_id = int(parts[1])
        chat_id = int(parts[2])
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        thread_id: Optional[int] = None
        destination = db.get_destination_for_category(material.category_id)
        if destination and destination[0] == chat_id:
            thread_id = destination[1]

        try:
            await send_material_to_chat(
                application=context.application,
                chat_id=chat_id,
                material=material,
                db=db,
                thread_id=thread_id,
            )
        except Exception:
            await query.edit_message_text(
                "Не смог отправить в группу. Проверь, что бот добавлен в группу и у него есть право писать.",
                reply_markup=material_view_keyboard(material_id, is_admin=is_admin),
            )
            return

        await query.edit_message_text(
            "Отправлено ✅",
            reply_markup=material_view_keyboard(material_id, is_admin=is_admin),
        )
        return

    if data.startswith("ADD_PICKCAT_"):
        if not is_admin:
            await query.answer(
                "Только администратор может добавлять материалы",
                show_alert=True,
            )
            return

        clear_add_state(context)
        category_id = int(data.replace("ADD_PICKCAT_", "").strip())
        category = db.get_category(category_id)
        if category is None:
            await query.edit_message_text(
                "Категория не найдена.",
                reply_markup=categories_keyboard(db),
            )
            return

        context.user_data["add_category_id"] = category_id
        context.user_data["add_file_id"] = ""
        context.user_data["add_link"] = ""
        context.user_data["add_tags"] = ""

        await query.edit_message_text(
            f"Категория: {category.icon} {category.name}\n\nТеперь пришли заголовок материала одним сообщением.",
            reply_markup=add_cancel_keyboard(),
        )
        context.user_data["awaiting_add_title"] = True
        return

    if data == "NOOP":
        return
