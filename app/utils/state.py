from __future__ import annotations

from typing import TYPE_CHECKING

from app.constants import ADD_STATE_KEYS, PEPE_MODE_KEY, PEPE_STATE_KEYS, SEARCH_STATE_KEYS

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

def clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ADD_STATE_KEYS:
        context.user_data.pop(key, None)


def enable_pepe_mode(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[PEPE_MODE_KEY] = True


def disable_pepe_mode(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in PEPE_STATE_KEYS:
        context.user_data.pop(key, None)


def is_pepe_mode_enabled(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return context.user_data.get(PEPE_MODE_KEY) is True


def clear_interaction_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_add_state(context)
    for key in SEARCH_STATE_KEYS:
        context.user_data.pop(key, None)
    disable_pepe_mode(context)
