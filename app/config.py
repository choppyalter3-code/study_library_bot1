import os
from dataclasses import dataclass


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    admin_user_id: int
    run_mode: str
    port: int
    render_external_url: str
    webhook_path: str
    webhook_secret: str
    database_path: str
    database_url: str


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Check .env locally or Environment Variables on Render."
        )
    return value


def load_config() -> Config:
    run_mode = os.getenv("RUN_MODE", "polling").strip().lower() or "polling"
    if run_mode not in {"polling", "webhook"}:
        raise RuntimeError("RUN_MODE must be either polling or webhook.")

    admin_user_id_raw = require_env("ADMIN_USER_ID")
    if not admin_user_id_raw.isdigit():
        raise RuntimeError("ADMIN_USER_ID must be a numeric Telegram user id.")

    try:
        port = int(os.getenv("PORT", "10000"))
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer.") from exc

    render_external_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()

    if run_mode == "webhook":
        if not render_external_url:
            raise RuntimeError("RENDER_EXTERNAL_URL is required when RUN_MODE=webhook.")
        if not webhook_secret:
            raise RuntimeError("WEBHOOK_SECRET is required when RUN_MODE=webhook.")

    return Config(
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        admin_user_id=int(admin_user_id_raw),
        run_mode=run_mode,
        port=port,
        render_external_url=render_external_url,
        webhook_path=os.getenv("WEBHOOK_PATH", "telegram").strip().strip("/") or "telegram",
        webhook_secret=webhook_secret,
        database_path=os.getenv(
            "DATABASE_PATH",
            os.path.join(BASE_DIR, "data", "study_library.sqlite3"),
        ).strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
    )
