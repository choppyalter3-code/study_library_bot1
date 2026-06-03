from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📚 Библиотека", callback_data="MENU_LIBRARY")],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="MENU_SEARCH")],
    ]

    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text="➕ Добавить материал", callback_data="MENU_ADD")]
        )

    return InlineKeyboardMarkup(keyboard)


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="MENU_MAIN")]]
    )


def add_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text="Отменить добавление", callback_data="ADD_CANCEL")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="MENU_MAIN")],
        ]
    )


def categories_keyboard(db) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []
    for category in db.list_categories():
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{category.icon} {category.name}",
                    callback_data=f"CATEGORY_{category.category_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(keyboard)


def materials_keyboard(db, category_id: int) -> InlineKeyboardMarkup:
    materials = db.list_materials_by_category(category_id)
    keyboard: List[List[InlineKeyboardButton]] = []

    if not materials:
        keyboard.append(
            [InlineKeyboardButton(text="(Материалов пока нет)", callback_data="NOOP")]
        )
    else:
        for material in materials[:30]:
            title = material.title if material.title else "Без названия"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=title[:45],
                        callback_data=f"MATERIAL_{material.material_id}",
                    )
                ]
            )

    keyboard.append(
        [
            InlineKeyboardButton(text="⬅️ К категориям", callback_data="MENU_LIBRARY"),
            InlineKeyboardButton(text="🏠 В меню", callback_data="MENU_MAIN"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def material_view_keyboard(material_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []

    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text="📣 Отправить в группу", callback_data=f"SEND_{material_id}")]
        )

    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="BACK_FROM_MATERIAL")])
    keyboard.append([InlineKeyboardButton(text="🏠 В меню", callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(keyboard)


def groups_keyboard(db, material_id: int) -> InlineKeyboardMarkup:
    groups = db.list_groups()
    keyboard: List[List[InlineKeyboardButton]] = []
    if not groups:
        keyboard.append(
            [InlineKeyboardButton(text="(Группы не зарегистрированы)", callback_data="NOOP")]
        )
    else:
        for chat_id, title in groups[:20]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=title[:45],
                        callback_data=f"SENDTO_{material_id}_{chat_id}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"MATERIAL_{material_id}")])
    return InlineKeyboardMarkup(keyboard)
