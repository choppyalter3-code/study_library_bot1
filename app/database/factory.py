from app.config import Config
from app.database.base import BaseDatabase
from app.database.postgres import PostgresDatabase
from app.database.sqlite import SQLiteDatabase


def create_database(config: Config) -> BaseDatabase:
    if config.database_url:
        return PostgresDatabase(config.database_url, config.admin_user_id)
    return SQLiteDatabase(config.database_path, config.admin_user_id)
