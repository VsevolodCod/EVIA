# Прямой PostgreSQL-источник

EVIA может читать указанные таблицы PostgreSQL напрямую. CSV остаётся независимым
режимом: если переменные ниже не заданы или PostgreSQL временно недоступен,
загрузка CSV и локальная DuckDB-аналитика продолжают работать.

## Настройка

Задайте переменные окружения backend-сервиса EVIA:

```dotenv
POSTGRES_DSN=postgresql://evia_reader:password@postgres.internal:5432/analytics
POSTGRES_ALLOWED_TABLES=public.orders,analytics.events
POSTGRES_CONNECT_TIMEOUT_SECONDS=5
POSTGRES_STATEMENT_TIMEOUT_MS=10000
```

`POSTGRES_ALLOWED_TABLES` обязателен для включения источника: каждая запись имеет
строгий вид `schema.table`. После запуска EVIA обнаруживает только эти реально
существующие таблицы и показывает их среди обычных источников.

На Railway добавьте `POSTGRES_DSN` в Variables EVIA как reference на приватный
`DATABASE_URL` сервиса Postgres, например `${{Postgres.DATABASE_URL}}`. Браузеру
не нужен и не должен быть доступен адрес PostgreSQL: он продолжает обращаться
только к публичному EVIA URL.

## Права пользователя

DSN должен принадлежать отдельной роли с минимальными правами. Пример для одной
таблицы:

```sql
CREATE ROLE evia_reader LOGIN PASSWORD 'use-a-secret-manager';
GRANT CONNECT ON DATABASE analytics TO evia_reader;
GRANT USAGE ON SCHEMA public TO evia_reader;
GRANT SELECT ON public.orders TO evia_reader;
```

EVIA дополнительно открывает новую транзакцию `READ ONLY` для каждой операции,
устанавливает локальный `statement_timeout`, разрешает только настроенные таблицы
и пропускает только ограниченный аналитический `SELECT`. Пароль и DSN не
сохраняются в каталоге, не отправляются модели, не возвращаются API и не
логируются.

## Проверка

`GET /sources/postgresql/status` возвращает только:

```json
{"configured": true, "connected": true}
```

Он не раскрывает строку подключения, имя пользователя, адрес или детали ошибки.
Для локальной приёмки используйте:

```bash
./scripts/verify_postgresql_source.sh
```

Скрипт поднимает временный PostgreSQL 16, создаёт read-only роль, проверяет
allowlist, обновление данных внешним соединением, неверный пароль, timeout и
последующий успешный запрос, затем удаляет контейнер и volume.
