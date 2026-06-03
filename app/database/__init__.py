from app.database.base import BaseDatabase
from app.database.factory import create_database
from app.database.postgres import PostgresDatabase
from app.database.sqlite import SQLiteDatabase


# Backward-compatible name for older imports in small local scripts.
Database = SQLiteDatabase

__all__ = [
    "BaseDatabase",
    "Database",
    "PostgresDatabase",
    "SQLiteDatabase",
    "create_database",
]
