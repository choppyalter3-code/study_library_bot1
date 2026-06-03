from telegram.ext import ContextTypes

from app.constants import ADD_STATE_KEYS, SEARCH_STATE_KEYS


def clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ADD_STATE_KEYS:
        context.user_data.pop(key, None)


def clear_interaction_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_add_state(context)
    for key in SEARCH_STATE_KEYS:
        context.user_data.pop(key, None)
