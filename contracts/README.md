# EVIA: контракт 1.0 (#4)

Источник схем — `app/contracts/v1.py`, экспорт — `python -m scripts.export_contracts`. Публикуемые JSON Schema Draft 2020-12 находятся в `contracts/v1/`, синтетические примеры — `fixtures/`. `python -m pytest tests/test_contracts.py` проверяет Pydantic, независимый JSON Schema validator, ограничения таблиц и отсутствие расхождения экспорта с моделями.

## Работающий API и следующий контракт

Текущие `/sources`, `/sources/{id}/schema`, `/preview`, `/profile`, `/agent/ask`, `/agent/chat`, `/chats` остаются совместимы с `app/models.py` и `frontend/src/api.ts`. `/agent/ask` по-прежнему возвращает `answer`, `steps`, `tool_results`, необязательный `chat_id`; источник передаётся в `source_ids`. `Source`, `SourceSchema` используют действующие модели, `Profile` отражает действующий payload. Fixtures `source`, `profile`, `success` проверяются также настоящим frontend API parser.

`DatasetSnapshot`, `QueryResult`, расширенный `AgentResponse` и `Error` — **целевой контракт для следующих задач**, а не объявление реализованного SQL, графиков, задач или `/v1` endpoints. Текущие ошибки FastAPI имеют `{detail}` и HTTP status; они не выдаются за уже внедрённый Error 1.0. Внедрение request_id/error envelope в runtime выполняется явно в следующих интеграционных задачах. SQL-строка в fixture — текст примера, её наличие не означает выполненный запрос.

## Идентификаторы и версии

- `source_id`: стабильный непрозрачный ID источника; имя/имя файла не используется как ключ. `Source.status=available` — существующий статус CSV, не синоним готового SQL snapshot.
- `snapshot_id`: отдельный неизменяемый снимок данных. CSV-импорт сохраняет его в `Source.snapshot_id` и публикует источник только после материализации в DuckDB. Повторный импорт создаёт новый snapshot; старый результат продолжает ссылаться на старую версию. Публикация `ready` атомарна; `importing/failed` нельзя использовать для аналитики. Отдельный snapshot API и история снимков пока не реализованы.
- `schema_version`: монотонная версия схемы источника; `parser_version` — версия интерпретатора CSV, это разные понятия. `content_sha256` характеризует исходные байты. Нулевой hash в fixture вымышленный.
- `request_id`: непустой ID одной попытки запроса, назначается сервером; при повторе новая попытка получает новый ID. Это не ключ идемпотентности. Вложенная ошибка содержит тот же ID. Не включать секреты, имена файлов и персональные данные в ID.
- `chat_id`, `artifact_ids`, `job_id`: непрозрачные ссылки; `null`/пустой список означает отсутствие, не незавершённую реализацию. Семантика постоянных чатов описана в отдельной #16; UI использует `/agent/chat` с одним `chat_id` на диалог. Восстановление списка сессий после перезагрузки ещё относится к #18.
- `contract_version=1.0`: несовместимое изменение типов/смысла/обязательных полей требует нового major и нового каталога. Minor добавляет необязательные поля; читатели игнорируют неизвестные поля, но проверяют обязательные типы. Новые значения enum согласуются с потребителями до выпуска. Не удалять legacy-поля до миграции UI.

## Факты и объяснения

`AgentResponse.analysis` содержит `intent`, `sql`, `explanation`. Эти поля не являются вычисленным результатом. Факты находятся в `results`: упорядоченные `columns`, позиционные `rows`, `returned_rows`, `row_limit`, `truncated`, `elapsed_ms`, `provenance`. `provenance` указывает источник, snapshot, версию схемы, инструмент и время исполнения; JOIN требует происхождение всех входов. Синтетические fixtures не используются как ответы приложения.

`returned_rows == len(rows) <= row_limit`, ширина каждой строки совпадает с columns; SQL-алиасы должны быть уникальными. Пустая таблица — `rows=[]`, `returned_rows=0`, с сохранёнными columns, не число ноль. `truncated` сообщает об ограничении результата; точный общий COUNT нельзя выводить из него. DECIMAL передаётся строкой с точкой, без округления через float; ID остаётся строкой. `null` обозначает NULL, `0` — число, пустая строка — строку. JSON Schema проверяет структуру, Pydantic — также межполевые инварианты.

`status=clarification` не содержит выполненных results; `status=error` требует Error. Коды: `VALIDATION_ERROR`, `SOURCE_NOT_FOUND`, `IMPORT_FAILED`, `QUERY_REJECTED`, `QUERY_TIMEOUT`, `MODEL_UNAVAILABLE`, `INTERNAL_ERROR`. В message нельзя включать credentials, raw SQL с чувствительными литералами, stacktrace или строки исходных данных. `retryable` указывает допустимость повтора, но не запускает его автоматически.

## Владельцы границ

| Модуль | Зона | Выдаёт / принимает | Проверка |
| --- | --- | --- | --- |
| Источники, импорт, каталог, Data Engine | B | Source, SourceSchema, DatasetSnapshot, Profile, QueryResult | schema/query/empty fixtures; SQL и типы — #6/#7/#9 |
| Агент и LLM | A | AnalysisPlan и AgentResponse поверх фактических QueryResult | success/clarification/failure; не подменять rows текстом LLM |
| FastAPI, HTTP, chats, UI | C | Валидация, request_id/errors, отображение legacy и новых полей | frontend parser, JSON schema tests, compatibility tests |

Это зоны, а не назначенные люди. Контракт готов к командному review; согласование A/B/C не объявляется состоявшимся. PR должен ссылаться `Closes #4`, но issue остаётся открытой до review/merge.
