import logging

from dotenv import load_dotenv
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.config import load_config
from app.database import create_database
from app.handlers.admin import (
    bind_category_command,
    cancel_command,
    register_group_command,
    start_command,
)
from app.handlers.deadlines import check_deadlines, deadline_command, deadlines_command
from app.handlers.materials import file_router, ignore_non_command_messages_in_groups
from app.handlers.menu import menu_callback
from app.handlers.pepe import pepe_command
from app.handlers.search import text_router


load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("study_library_bot")


def build_application() -> Application:
    config = load_config()
    db = create_database(config)
    logger.info("Database backend: %s", db.backend_name)

    application = Application.builder().token(config.telegram_bot_token).build()
    application.bot_data["config"] = config
    application.bot_data["db"] = db

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("register", register_group_command))
    application.add_handler(CommandHandler("bind_category", bind_category_command))
    application.add_handler(CommandHandler("deadline", deadline_command))
    application.add_handler(CommandHandler("deadlines", deadlines_command))
    application.add_handler(CommandHandler("pepe", pepe_command))

    application.add_handler(CallbackQueryHandler(menu_callback))

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.ALL,
            file_router,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            ignore_non_command_messages_in_groups,
        )
    )

    application.job_queue.run_repeating(
        lambda context: check_deadlines(context.application),
        interval=3600,
        first=60,
    )

    return application


def main() -> None:
    application = build_application()
    config = application.bot_data["config"]

    logger.info("RUN_MODE=%s", config.run_mode)

    if config.run_mode == "polling":
        logger.info("Bot starts in polling mode")
        application.run_polling(drop_pending_updates=True)
        return

    webhook_url = f"{config.render_external_url}/{config.webhook_path}"

    logger.info("Bot starts in webhook mode")
    logger.info("PORT: %s", config.port)
    logger.info("Webhook URL: %s", webhook_url)

    application.run_webhook(
        listen="0.0.0.0",
        port=config.port,
        url_path=config.webhook_path,
        webhook_url=webhook_url,
        secret_token=config.webhook_secret,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
