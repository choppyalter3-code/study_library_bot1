import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from app.services.deadlines_service import format_deadline_date, parse_deadline_date
from app.services.materials_service import escape_html
from app.utils.context import get_db
from app.utils.security import require_admin


logger = logging.getLogger("study_library_bot")


async def deadline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)

    if update.effective_message is None:
        return

    if not require_admin(update, db):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Использование:\n/deadline 15.03 Лабораторная №3"
        )
        return

    deadline_date_input = context.args[0]
    deadline_date = parse_deadline_date(deadline_date_input)
    text = " ".join(context.args[1:]).strip()

    if deadline_date is None:
        await update.effective_message.reply_text(
            "Некорректная дата. Используй формат YYYY-MM-DD, DD.MM.YYYY или DD.MM."
        )
        return

    if not text:
        await update.effective_message.reply_text("Напиши описание дедлайна.")
        return

    db.add_deadline(text, deadline_date)
    deadline_display = format_deadline_date(deadline_date)

    deadline_message = (
        f"📅 <b>Дедлайн</b>\n\n"
        f"{escape_html(text)}\n"
        f"Сдать до: <b>{escape_html(deadline_display)}</b>"
    )

    category = db.get_category_by_name("Дедлайны")
    if category is not None:
        destination = db.get_destination_for_category(category.category_id)
        if destination:
            chat_id, thread_id = destination
            try:
                await context.application.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=deadline_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as error:
                logger.error("Ошибка отправки дедлайна в тему: %s", error)

    await update.effective_message.reply_text(
        deadline_message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def check_deadlines(application: Application):
    db = application.bot_data["db"]
    deadlines = db.list_deadlines()
    if not deadlines:
        return

    now = datetime.utcnow()
    for row in deadlines:
        text = row["text"]
        date_str = row["deadline_date"]
        reminded_at = row["reminded_at"]

        if reminded_at:
            continue

        try:
            deadline_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        delta = deadline_date - now
        if 0 < delta.total_seconds() < 86400:
            category = db.get_category_by_name("Дедлайны")
            if category is None:
                continue

            destination = db.get_destination_for_category(category.category_id)
            if not destination:
                continue

            chat_id, thread_id = destination
            message = (
                f"⚠️ <b>Напоминание о дедлайне</b>\n\n"
                f"{escape_html(text)}\n"
                f"Сдать до: <b>{escape_html(format_deadline_date(date_str))}</b>"
            )

            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                )
                db.mark_deadline_reminded(int(row["deadline_id"]))
            except Exception as error:
                logger.error("Ошибка напоминания о дедлайне: %s", error)


async def deadlines_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)

    if update.effective_message is None:
        return

    deadlines = db.list_deadlines()
    if not deadlines:
        await update.effective_message.reply_text(
            "📅 Пока нет сохранённых дедлайнов."
        )
        return

    lines = ["📅 <b>Ближайшие дедлайны</b>\n"]
    for row in deadlines:
        text = escape_html(row["text"])
        date = escape_html(format_deadline_date(row["deadline_date"]))
        notified = " · напоминание отправлено" if row["reminded_at"] else ""
        lines.append(f"• {text} — <b>{date}</b>{notified}")

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )
