# Исправления замечаний PR #69

Основа: `adb11d3ddd75f346bba0010e96a453955aab46b3`.
Ревью: https://github.com/VsevolodCod/EVIA/pull/69#pullrequestreview-5601199271.

## Поведение

- Числовые CAST/TRY_CAST в CSV-плане нормализуют десятичную запятую в точку.
  Пустая строка после TRIM становится NULL; непустое нечисловое значение вызывает
  QUERY_REJECTED, а не молча исключается из суммы. Исходный CSV, предпросмотр и ID
  с ведущими нулями не меняются. В `analysis.sql` возвращается фактически исполненный SQL.
- Нормализация не допускает несколько SQL-выражений. SafeQueryExecutor разрешает
  строковую функцию REPLACE, сохраняя запрет DML, внешних функций и побочных эффектов.
- CTE не может затенить разрешённую исходную таблицу, включая другой регистр имени.
  Обычный CTE с другим именем поверх `source` продолжает работать.
- Пустое продолжение после `length` и неизвестная причина завершения не дают
  статус answered. Ollama должен подтвердить `done=true`; mock явно сообщает завершение.
- Ответ со статусом error не сохраняется как сообщение assistant. При открытии
  истории оставшийся вопрос отображается с повтором. Загруженный chat_id используется
  при повторе: новый чат не создаётся.

## Тесты, которые уже были в PR

| Файл | Проверки |
| --- | --- |
| `tests/test_csv_query_agent.py` | SUM/COUNT с реальным DuckDB; одна попытка исправления SQL; пустой результат; malformed JSON; константные проекции; datetime; таймаут/недоступность; обрезанный JSON-план |
| `tests/test_agent.py` | Mock, передача истории, непустое продолжение после length, исчерпание лимита |
| `tests/test_safe_sql.py` | Read-only SQL, лимиты, CTE, запрет внешнего доступа и опасных выражений |
| `tests/test_chat_persistence.py` | SQLite, повторное открытие, пагинация, конкурентные записи |
| `frontend/src/App.test.tsx` | Текущая ошибка с повтором, изоляция источников, история и обычный повтор |
| `frontend/src/features/results/AnalysisResult.test.tsx` | Таблица/показатель и происхождение результата |

## Добавленные регрессии

| Тест | Что доказывает |
| --- | --- |
| `test_numeric_aggregate_preserves_comma_dot_empty_and_raw_ids` (2 случая) | SUM=301, AVG=150.5 для 120,5 и 180.5; пустоты допустимы; ID 001 сохраняется; возвращённый SQL воспроизводим |
| `test_invalid_number_beyond_schema_sample_cannot_silently_disappear` | Невалидное 501-е значение за пределами выборки схемы не исключается молча |
| `test_shadowed_source_is_rejected_but_real_source_cte_is_allowed` (3) | Подмена source отклоняется, правильный CTE после исправления возвращает 300 |
| `test_cte_cannot_shadow_allowed_source` (3) | Запрет действует и при прямом вызове исполнителя, включая SOURCE и quoted Source |
| `test_numeric_normalization_cannot_discard_a_second_statement` | Переписывание CAST не превращает два SQL-выражения в разрешённое одно |
| `test_empty_or_unconfirmed_continuation_never_completes_partial_answer` (3) | Пустота, пробелы и неизвестное завершение не делают обрыв готовым ответом |
| `test_provider_without_completion_confirmation_is_not_successful` (2) | Ollama done=false и OpenAI без finish_reason дают ошибку |
| `test_csv_plan_without_completion_metadata_never_executes` | Даже валидный JSON без подтверждённого завершения не исполняется |
| `test_failed_chat_reply_is_not_persisted_as_success_and_retry_uses_same_chat` | Реальный FastAPI/SQLite: ошибка не становится assistant, повтор остаётся в прежнем чате |
| `reopens an unanswered request as an error and retries in the same chat` | Компонент: после открытия истории доступен повтор; запрос использует прежний chat_id |

## Воспроизведение

```sh
LLM_PROVIDER=mock python -m pytest -q -rs
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

На Windows переменную задают через `$env:LLM_PROVIDER='mock'` в PowerShell.
Среда проверки: Python из подготовленного venv, Node 24, DuckDB; данные синтетические.
Итог 21.10.2026: **153 backend passed / 6 skipped**, **86 frontend passed**,
TypeScript и production build успешны. По сравнению с исходным PR добавлено
17 backend-проверок (с учётом параметризации) и 1 компонентная проверка.
Opt-in browser и PostgreSQL без тестовых DSN пропускаются; POSIX process-group и
symlink-проверка требуют соответствующей платформы/прав.

Это регрессии исполнения и сохранения, а не бенчмарк качества живой LLM.
Нормализация относится к явным числовым приведениям в CSVQueryAgent, не к произвольным
запросам внешних клиентов. Запятая трактуется как десятичный знак, как и при выводе
типа CSV; разделители тысяч не поддерживаются. Проверка source ограничивает структуру
SQL, но не доказывает соответствие произвольного запроса смыслу вопроса пользователя.
Текст старых ошибок, уже сохранённых как assistant, автоматически не мигрируется.
