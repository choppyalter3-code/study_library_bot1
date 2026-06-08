from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.keyboards import (
    add_cancel_keyboard,
    back_to_main_keyboard,
    categories_keyboard,
    favorites_keyboard,
    groups_keyboard,
    main_menu_keyboard,
    material_view_keyboard,
    materials_keyboard,
)
from app.services.analytics_service import format_admin_statistics
from app.services.materials_service import format_material_text
from app.services.telegram_service import send_material_to_chat
from app.services.views_service import log_material_view
from app.utils.chat import is_private_chat
from app.utils.context import get_db
from app.utils.favorites import is_favorite
from app.utils.security import require_admin
from app.utils.state import clear_add_state, clear_interaction_state
from app.utils.users import get_or_create_user_from_update


ORIGIN_MAIN = "MAIN"
ORIGIN_FAVORITES = "FAV"
ORIGIN_LIBRARY_PREFIX = "LIB-"


def _library_origin(category_id: int) -> str:
    return f"{ORIGIN_LIBRARY_PREFIX}{category_id}"


def _category_id_from_origin(origin: str) -> Optional[int]:
    if not origin.startswith(ORIGIN_LIBRARY_PREFIX):
        return None

    raw_category_id = origin.removeprefix(ORIGIN_LIBRARY_PREFIX)
    if not raw_category_id.isdigit():
        return None

    category_id = int(raw_category_id)
    return category_id if category_id > 0 else None


def _is_valid_origin(origin: Optional[str]) -> bool:
    if origin in {ORIGIN_MAIN, ORIGIN_FAVORITES}:
        return True
    if origin is None:
        return False
    return _category_id_from_origin(origin) is not None


def _parse_material_origin_callback(data: str, prefix: str) -> tuple[int, Optional[str]]:
    tail = data.removeprefix(prefix)
    raw_material_id, _, origin = tail.partition("_")
    return int(raw_material_id), origin or None


def _parse_sendto_callback(data: str) -> tuple[int, int, Optional[str]]:
    parts = data.removeprefix("SENDTO_").split("_", 2)
    if len(parts) < 2:
        raise ValueError("Invalid SENDTO callback")
    origin = parts[2] if len(parts) == 3 else None
    return int(parts[0]), int(parts[1]), origin


def _back_callback_from_message(query) -> Optional[str]:
    message = query.message
    reply_markup = getattr(message, "reply_markup", None)
    if reply_markup is None:
        return None

    for row in reply_markup.inline_keyboard:
        for button in row:
            callback_data = getattr(button, "callback_data", None)
            text = getattr(button, "text", "") or ""
            if callback_data and text.startswith("⬅"):
                return str(callback_data)

    return None


def _origin_from_back_callback(back_callback: Optional[str], material) -> Optional[str]:
    if back_callback is None:
        return None
    if back_callback == "MENU_MAIN":
        return ORIGIN_MAIN
    if back_callback == "MENU_FAVORITES":
        return ORIGIN_FAVORITES
    if back_callback.startswith("CATEGORY_"):
        raw_category_id = back_callback.removeprefix("CATEGORY_")
        if raw_category_id.isdigit():
            return _library_origin(int(raw_category_id))
    if back_callback.startswith("FAV_MATERIAL_"):
        return ORIGIN_FAVORITES
    if back_callback.startswith("MATERIAL_"):
        try:
            _, origin = _parse_material_origin_callback(back_callback, "MATERIAL_")
        except ValueError:
            origin = None
        if _is_valid_origin(origin):
            return origin
        return None
    if back_callback == "BACK_FROM_MATERIAL":
        return _library_origin(material.category_id)
    return None


def _resolve_origin(origin: Optional[str], query, material) -> str:
    if _is_valid_origin(origin):
        return str(origin)

    inferred_origin = _origin_from_back_callback(
        _back_callback_from_message(query),
        material,
    )
    if _is_valid_origin(inferred_origin):
        return str(inferred_origin)

    return _library_origin(material.category_id)


def _back_callback_for_origin(origin: str, material) -> str:
    if origin == ORIGIN_MAIN:
        return "MENU_MAIN"
    if origin == ORIGIN_FAVORITES:
        return "MENU_FAVORITES"

    category_id = _category_id_from_origin(origin) or material.category_id
    return f"CATEGORY_{category_id}"


def _material_callback_for_origin(material_id: int, origin: str) -> str:
    return f"MATERIAL_{material_id}_{origin}"


async def _show_material_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    material,
    is_admin: bool,
    origin: str,
    log_view: bool = False,
) -> None:
    query = update.callback_query
    if query is None:
        return

    db = get_db(context)
    user_id = get_or_create_user_from_update(db, update)
    favorite_state = False
    if user_id is not None:
        if log_view:
            log_material_view(db, user_id, material.material_id)
        favorite_state = is_favorite(db, user_id, material.material_id)

    await query.edit_message_text(
        format_material_text(material, db),
        parse_mode=ParseMode.HTML,
        reply_markup=material_view_keyboard(
            material.material_id,
            is_admin=is_admin,
            is_favorite=favorite_state,
            back_callback=_back_callback_for_origin(origin, material),
            origin=origin,
        ),
        disable_web_page_preview=True,
    )


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

    if data == "MENU_FAVORITES":
        clear_interaction_state(context)
        user_id = get_or_create_user_from_update(db, update)
        if user_id is None:
            await query.edit_message_text(
                "Не смог определить пользователя.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        favorites = db.list_favorites(user_id)
        text = "⭐ Избранное\nМатериалы:" if favorites else "⭐ Избранное\nПока пусто."
        await query.edit_message_text(
            text,
            reply_markup=favorites_keyboard(favorites),
        )
        return

    if data == "MENU_ANALYTICS":
        clear_interaction_state(context)
        if not is_admin:
            await query.answer(
                "Только администратор может смотреть статистику",
                show_alert=True,
            )
            return

        await query.edit_message_text(
            format_admin_statistics(db),
            reply_markup=back_to_main_keyboard(),
        )
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

    if data.startswith("FAV_MATERIAL_"):
        clear_interaction_state(context)
        material_id, origin = _parse_material_origin_callback(data, "FAV_MATERIAL_")
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        resolved_origin = _resolve_origin(origin or ORIGIN_FAVORITES, query, material)
        await _show_material_card(
            update,
            context,
            material,
            is_admin,
            resolved_origin,
            log_view=True,
        )
        return

    if data.startswith("MATERIAL_"):
        clear_interaction_state(context)
        material_id, origin = _parse_material_origin_callback(data, "MATERIAL_")
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        resolved_origin = _resolve_origin(origin, query, material)
        await _show_material_card(
            update,
            context,
            material,
            is_admin,
            resolved_origin,
            log_view=True,
        )
        return

    if data.startswith("FAVORITE_ADD_") or data.startswith("FAVORITE_REMOVE_"):
        add_to_favorites = data.startswith("FAVORITE_ADD_")
        prefix = "FAVORITE_ADD_" if add_to_favorites else "FAVORITE_REMOVE_"
        material_id, origin = _parse_material_origin_callback(data, prefix)
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        user_id = get_or_create_user_from_update(db, update)
        if user_id is None:
            await query.edit_message_text(
                "Не смог определить пользователя.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        if add_to_favorites:
            db.add_favorite(user_id, material_id)
            favorite_state = True
        else:
            db.remove_favorite(user_id, material_id)
            favorite_state = False

        resolved_origin = _resolve_origin(origin, query, material)
        await query.edit_message_text(
            format_material_text(material, db),
            parse_mode=ParseMode.HTML,
            reply_markup=material_view_keyboard(
                material.material_id,
                is_admin=is_admin,
                is_favorite=favorite_state,
                back_callback=_back_callback_for_origin(resolved_origin, material),
                origin=resolved_origin,
            ),
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

        material_id, origin = _parse_material_origin_callback(data, "SEND_")
        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        resolved_origin = _resolve_origin(origin, query, material)
        await query.edit_message_text(
            "Куда отправляем? Выбери группу:",
            reply_markup=groups_keyboard(
                db,
                material_id,
                back_callback=_material_callback_for_origin(material_id, resolved_origin),
                origin=resolved_origin,
            ),
        )
        return

    if data.startswith("SENDTO_"):
        if not is_admin:
            await query.answer(
                "Только администратор может отправлять материалы в группу",
                show_alert=True,
            )
            return

        try:
            material_id, chat_id, origin = _parse_sendto_callback(data)
        except ValueError:
            await query.edit_message_text(
                "Некорректная кнопка.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        material = db.get_material(material_id)
        if material is None:
            await query.edit_message_text(
                "Материал не найден.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        user_id = get_or_create_user_from_update(db, update)
        favorite_state = (
            user_id is not None and is_favorite(db, user_id, material.material_id)
        )
        resolved_origin = _resolve_origin(origin, query, material)
        back_callback = _back_callback_for_origin(resolved_origin, material)

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
                reply_markup=material_view_keyboard(
                    material_id,
                    is_admin=is_admin,
                    is_favorite=favorite_state,
                    back_callback=back_callback,
                    origin=resolved_origin,
                ),
            )
            return

        await query.edit_message_text(
            "Отправлено ✅",
            reply_markup=material_view_keyboard(
                material_id,
                is_admin=is_admin,
                is_favorite=favorite_state,
                back_callback=back_callback,
                origin=resolved_origin,
            ),
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
