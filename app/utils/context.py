from telegram.ext import ContextTypes

from app.database import BaseDatabase


def get_db(context: ContextTypes.DEFAULT_TYPE) -> BaseDatabase:
    return context.application.bot_data["db"]
