# study_library_bot1

Telegram-бот для учебной библиотеки: материалы по категориям, поиск, дедлайны и отправка материалов в группу/тему форума.

## Локальный запуск

1. Создай виртуальное окружение и установи зависимости:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Скопируй пример переменных окружения:

```bash
copy .env.example .env
```

3. Заполни `.env`.

4. Для локального режима оставь:

```env
RUN_MODE=polling
DATABASE_URL=
DATABASE_PATH=data/study_library.sqlite3
```

5. Запусти бота:

```bash
python bot.py
```

По умолчанию используется `polling` и локальная SQLite-база `data/study_library.sqlite3`.

## Запуск на Render

1. Создай Web Service.
2. Build command:

```bash
pip install -r requirements.txt
```

3. Start command:

```bash
python bot.py
```

4. Для Render/production поставь:

```env
RUN_MODE=webhook
```

5. Добавь Environment Variables из списка ниже.

## Env-переменные

| Переменная | Обязательная | Описание |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | да | Токен Telegram-бота от BotFather. |
| `ADMIN_USER_ID` | да | Telegram user id администратора. |
| `RUN_MODE` | нет | `polling` для локального запуска или `webhook` для Render/production. По умолчанию `polling`. |
| `RENDER_EXTERNAL_URL` | только webhook | Публичный URL сервиса Render без слеша в конце. |
| `WEBHOOK_SECRET` | только webhook | Секрет webhook. Используй длинную случайную строку. |
| `WEBHOOK_PATH` | нет | Путь webhook, по умолчанию `telegram`. |
| `PORT` | нет | Порт web-сервера, по умолчанию `10000`. |
| `DATABASE_PATH` | нет | Путь к SQLite-базе, по умолчанию `data/study_library.sqlite3`. |
| `DATABASE_URL` | нет | PostgreSQL/Supabase connection string. Если пустая, используется SQLite. Если задана, используется PostgreSQL. |

В `RUN_MODE=polling` обязательны только `TELEGRAM_BOT_TOKEN` и `ADMIN_USER_ID`.
В `RUN_MODE=webhook` дополнительно обязательны `RENDER_EXTERNAL_URL` и `WEBHOOK_SECRET`.

## SQLite или PostgreSQL

Бот выбирает базу автоматически:

- `DATABASE_URL` пустая: используется `SQLiteDatabase` через `DATABASE_PATH`;
- `DATABASE_URL` задана: используется `PostgresDatabase`.

SQLite остаётся локальным fallback-режимом. Рабочую SQLite-базу нельзя хранить в GitHub: в ней могут оказаться `chat_id`, `file_id`, привязки тем, дедлайны и учебные материалы.

## PostgreSQL/Supabase smoke-test

Скрипт `scripts/smoke_test_database.py` проверяет текущую базу через factory `create_database(config)`.

Он проверяет:

- какой backend используется: `sqlite` или `postgres`;
- создание схемы;
- наличие таблиц `users`, `favorites`, `material_views`, `search_logs`;
- повторное `add_favorite` без создания дублей;
- методы `get_or_create_user`, `add_favorite`, `remove_favorite`, `list_favorites`, `log_search`, `log_material_view`.

Запуск для локального SQLite:

```bash
python scripts/smoke_test_database.py
```

Запуск для Supabase/PostgreSQL:

```bash
set DATABASE_URL=postgresql://...
python scripts/smoke_test_database.py
```

На PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://..."
python scripts/smoke_test_database.py
```

Скрипт завершится строкой `SUCCESS` или `ERROR: ...`. Тестовые строки создаются с префиксом smoke-test и удаляются в конце проверки.

## Подключение Supabase

1. Создай проект в Supabase.
2. Открой `Project Settings` -> `Database`.
3. Найди PostgreSQL connection string. Для Render обычно удобен URI-формат вида:

```text
postgresql://postgres.<project-ref>:<password>@aws-...pooler.supabase.com:6543/postgres
```

4. В Render добавь:

```env
DATABASE_URL=postgresql://...
RUN_MODE=webhook
RENDER_EXTERNAL_URL=https://your-render-service.onrender.com
WEBHOOK_SECRET=long-random-secret
TELEGRAM_BOT_TOKEN=...
ADMIN_USER_ID=...
```

5. Перезапусти сервис. В логах должна появиться строка:

```text
Database backend: postgres
```

Если `DATABASE_URL` пустая, в логах будет:

```text
Database backend: sqlite
```

При первом запуске PostgreSQL-режим создаёт/проверяет схему сам.

## Структура проекта

```text
app/
├── main.py
├── config.py
├── constants.py
├── keyboards.py
├── models.py
├── database/
│   ├── __init__.py
│   ├── base.py
│   ├── factory.py
│   ├── postgres.py
│   └── sqlite.py
├── handlers/
│   ├── __init__.py
│   ├── admin.py
│   ├── deadlines.py
│   ├── materials.py
│   ├── menu.py
│   └── search.py
├── services/
│   ├── __init__.py
│   ├── deadlines_service.py
│   ├── materials_service.py
│   ├── search_history_service.py
│   ├── telegram_service.py
│   └── views_service.py
└── utils/
    ├── __init__.py
    ├── chat.py
    ├── context.py
    ├── favorites.py
    ├── security.py
    ├── state.py
    └── users.py

scripts/
└── smoke_test_database.py
```

## Схема базы

Сохраняются текущие таблицы:

- `admins`
- `groups`
- `categories`
- `materials`
- `destinations`
- `deadlines`

Добавлены таблицы для роста базы и будущих функций:

- `users`
- `favorites`
- `material_views`
- `search_logs`

Слой базы создаёт индексы для пользователей, материалов, избранного, просмотров и поисковых логов.
