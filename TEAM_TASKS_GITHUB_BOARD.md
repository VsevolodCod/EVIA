# EVIA — командный backlog

Обновлено 17.10.2026. Задачи опубликованы в GitHub; это навигация, а не замена Issues.

[Доска команды](https://github.com/users/VsevolodCod/projects/2) · [Все задачи](https://github.com/VsevolodCod/Linza-BI/issues?q=is%3Aissue+is%3Aopen+label%3Atype%3Atask) · [Этапы](https://github.com/VsevolodCod/Linza-BI/milestones)

## Что уже существует

- Backend развивается в `tes/pipeline_1`; интеграционная ветка — `integration/linza-workspace`. `main` пока не отражает всю работу команды.
- [Issue #1](https://github.com/VsevolodCod/Linza-BI/issues/1) и [PR #2](https://github.com/VsevolodCod/Linza-BI/pull/2) содержат текущую работу над React-интерфейсом, CSV, Markdown, таблицами и EVIA. Повторный frontend bootstrap в backlog не добавлен.
- Основание аудита: backend `a27cefe`, frontend `26ea8c8`, integration `2fb0413`. Указанные в integration-документе тесты не выдаются за проверки, выполненные при создании этого backlog.
- Новые задачи описывают недостающие результаты. Ни одна задача разработки здесь не объявлена реализованной.

## Как читать и выбирать работу

- `role:A` — ML / AI Agent; `role:B` — ML / Data Intelligence; `role:C` — Fullstack / Product (Всеволод). Это рекомендуемые зоны, assignees оставлены пустыми до распределения командой.
- `priority:P0` — ближайший рабочий MVP; `priority:P1` — обязательный финальный объём; `priority:P2` — дополнительно после финальной приёмки. P0 не означает, что всё делается одновременно.
- `status:ready` — нет блокирующих issue-зависимостей; перед началом всё равно проверить контракт. `status:blocked` — зависимости перечислены в карточке. `status:backlog` — необязательный будущий объём. Эти метки не являются настроенными полями Status в Projects.
- Даты чекпоинтов, доступные часы и оборудование ещё требуют подтверждения. Milestones без вымышленных дедлайнов; S/M/L — относительная сложность, не человеко-дни.
- WIP: одна основная задача на участника. После снятия зависимостей обновить метку и статус доски; Done — после review, merge и приёмки.

## Первый параллельный шаг

- A: [#10](https://github.com/VsevolodCod/Linza-BI/issues/10) — локальные модели и железо.
- B: [#5](https://github.com/VsevolodCod/Linza-BI/issues/5) — аудит исходных CSV.
- C: [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) — контракты, затем [#3](https://github.com/VsevolodCod/Linza-BI/issues/3) — интеграция существующих работ после проверки #1/PR #2.

Далее: DuckDB → импорт → профиль и safe SQL → Text-to-SQL → вертикальный сценарий → benchmark и обзор → приёмка MVP. Задачи агента могут разрабатываться на согласованных fixtures параллельно Data Engine, но интеграционная приёмка требует реальных зависимостей.

## M1 · Рабочий MVP — 14 задач

| Issue | Результат | Зона | Размер | Зависимости |
|---|---|---|---|---|
| [#3](https://github.com/VsevolodCod/Linza-BI/issues/3) | Интеграция: собрать проверяемую общую ветку EVIA из текущих работ команды | C | M | #1 / PR #2 |
| [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) | API: зафиксировать контракты Agent, Data Engine и интерфейса | C | M | — |
| [#5](https://github.com/VsevolodCod/Linza-BI/issues/5) | Данные: воспроизводимый аудит всех девяти исходных CSV | B | M | — |
| [#6](https://github.com/VsevolodCod/Linza-BI/issues/6) | Data Engine: выполнять аналитику над CSV через DuckDB | B | M | [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#7](https://github.com/VsevolodCod/Linza-BI/issues/7) | Импорт CSV: типизация без потери строк и исходных значений | B | L | [#6](https://github.com/VsevolodCod/Linza-BI/issues/6), [#5](https://github.com/VsevolodCod/Linza-BI/issues/5) |
| [#8](https://github.com/VsevolodCod/Linza-BI/issues/8) | Профилирование: достоверный паспорт неизвестного датасета | B | M | [#7](https://github.com/VsevolodCod/Linza-BI/issues/7) |
| [#9](https://github.com/VsevolodCod/Linza-BI/issues/9) | SQL: безопасный read-only исполнитель с лимитами | B | L | [#6](https://github.com/VsevolodCod/Linza-BI/issues/6), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#10](https://github.com/VsevolodCod/Linza-BI/issues/10) | LLM: поднять локальный inference и выбрать два кандидата под железо | A | M | — |
| [#11](https://github.com/VsevolodCod/Linza-BI/issues/11) | Evals: подготовить 20 вопросов и независимые SQL-эталоны | B | M | [#5](https://github.com/VsevolodCod/Linza-BI/issues/5) |
| [#12](https://github.com/VsevolodCod/Linza-BI/issues/12) | Text-to-SQL: структурированная генерация по актуальной схеме | A | M | [#4](https://github.com/VsevolodCod/Linza-BI/issues/4), [#8](https://github.com/VsevolodCod/Linza-BI/issues/8), [#10](https://github.com/VsevolodCod/Linza-BI/issues/10) |
| [#13](https://github.com/VsevolodCod/Linza-BI/issues/13) | Агент: замкнуть CSV → вопрос → SQL → вычисленный ответ | A | M | [#12](https://github.com/VsevolodCod/Linza-BI/issues/12), [#9](https://github.com/VsevolodCod/Linza-BI/issues/9), [#3](https://github.com/VsevolodCod/Linza-BI/issues/3) |
| [#14](https://github.com/VsevolodCod/Linza-BI/issues/14) | Бенчмарк: сравнить две локальные модели на одном наборе вопросов | A | M | [#11](https://github.com/VsevolodCod/Linza-BI/issues/11), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13) |
| [#15](https://github.com/VsevolodCod/Linza-BI/issues/15) | Чекпоинт MVP: приёмка вертикального сценария и технических решений | C | S | [#14](https://github.com/VsevolodCod/Linza-BI/issues/14), [#8](https://github.com/VsevolodCod/Linza-BI/issues/8), [#22](https://github.com/VsevolodCod/Linza-BI/issues/22) |
| [#22](https://github.com/VsevolodCod/Linza-BI/issues/22) | Обзор данных: объяснять профиль и предлагать доступные вопросы | A | M | [#8](https://github.com/VsevolodCod/Linza-BI/issues/8), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13) |

## M2 · Обязательный финальный объём — 20 задач

| Issue | Результат | Зона | Размер | Зависимости |
|---|---|---|---|---|
| [#16](https://github.com/VsevolodCod/Linza-BI/issues/16) | Чаты: исправить сохранение persistent chat и защитить длинную историю | C | M | [#3](https://github.com/VsevolodCod/Linza-BI/issues/3), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#17](https://github.com/VsevolodCod/Linza-BI/issues/17) | Диалог: сохранять метрику, фильтры и источник между вопросами | A | M | [#16](https://github.com/VsevolodCod/Linza-BI/issues/16), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13), [#19](https://github.com/VsevolodCod/Linza-BI/issues/19) |
| [#18](https://github.com/VsevolodCod/Linza-BI/issues/18) | Интерфейс: подключить серверную историю и переключение диалогов | C | M | [#16](https://github.com/VsevolodCod/Linza-BI/issues/16), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#19](https://github.com/VsevolodCod/Linza-BI/issues/19) | Семантика: версионируемые контракты метрик и безопасные агрегаты | B | L | [#8](https://github.com/VsevolodCod/Linza-BI/issues/8), [#11](https://github.com/VsevolodCod/Linza-BI/issues/11) |
| [#20](https://github.com/VsevolodCod/Linza-BI/issues/20) | Агент: уточнения, неизвестные поля и неподдерживаемые вопросы | A | M | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13) |
| [#21](https://github.com/VsevolodCod/Linza-BI/issues/21) | Связи: обнаруживать ключи и предотвращать размножение сумм при JOIN | B | M | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#9](https://github.com/VsevolodCod/Linza-BI/issues/9) |
| [#23](https://github.com/VsevolodCod/Linza-BI/issues/23) | Источники: прямой PostgreSQL-коннектор с read-only запросами | B | L | [#9](https://github.com/VsevolodCod/Linza-BI/issues/9), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#24](https://github.com/VsevolodCod/Linza-BI/issues/24) | Интерфейс: подключение PostgreSQL и отчёт импорта CSV | C | M | [#23](https://github.com/VsevolodCod/Linza-BI/issues/23), [#7](https://github.com/VsevolodCod/Linza-BI/issues/7) |
| [#25](https://github.com/VsevolodCod/Linza-BI/issues/25) | Аналитика: группировки, дубликаты и объяснимые аномалии | B | M | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#9](https://github.com/VsevolodCod/Linza-BI/issues/9) |
| [#26](https://github.com/VsevolodCod/Linza-BI/issues/26) | Графики: типизированные артефакты и валидируемые спецификации | B | M | [#4](https://github.com/VsevolodCod/Linza-BI/issues/4), [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13) |
| [#27](https://github.com/VsevolodCod/Linza-BI/issues/27) | Интерфейс: графики в чате и переключение представлений | C | M | [#26](https://github.com/VsevolodCod/Linza-BI/issues/26), [#3](https://github.com/VsevolodCod/Linza-BI/issues/3) |
| [#28](https://github.com/VsevolodCod/Linza-BI/issues/28) | Дашборды: сохранять артефакты, компоновку и версии данных | C | M | [#26](https://github.com/VsevolodCod/Linza-BI/issues/26), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#29](https://github.com/VsevolodCod/Linza-BI/issues/29) | Агент: автоматически создавать осмысленный дашборд | A | M | [#28](https://github.com/VsevolodCod/Linza-BI/issues/28), [#22](https://github.com/VsevolodCod/Linza-BI/issues/22), [#26](https://github.com/VsevolodCod/Linza-BI/issues/26) |
| [#30](https://github.com/VsevolodCod/Linza-BI/issues/30) | Интерфейс: галерея и повторное открытие дашбордов | C | M | [#28](https://github.com/VsevolodCod/Linza-BI/issues/28), [#27](https://github.com/VsevolodCod/Linza-BI/issues/27), [#29](https://github.com/VsevolodCod/Linza-BI/issues/29) |
| [#31](https://github.com/VsevolodCod/Linza-BI/issues/31) | Результат: раскрываемый паспорт расчёта и безопасный экспорт | C | M | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#32](https://github.com/VsevolodCod/Linza-BI/issues/32) | Долгие операции: реальные статусы, отмена и восстановление после сбоя | C | L | [#13](https://github.com/VsevolodCod/Linza-BI/issues/13), [#7](https://github.com/VsevolodCod/Linza-BI/issues/7), [#4](https://github.com/VsevolodCod/Linza-BI/issues/4) |
| [#33](https://github.com/VsevolodCod/Linza-BI/issues/33) | Безопасность агента: prompt injection, минимизация данных и секреты | A | M | [#13](https://github.com/VsevolodCod/Linza-BI/issues/13), [#23](https://github.com/VsevolodCod/Linza-BI/issues/23) |
| [#34](https://github.com/VsevolodCod/Linza-BI/issues/34) | Поставка: единый локальный запуск и полностью автономный runtime | C | M | [#32](https://github.com/VsevolodCod/Linza-BI/issues/32), [#30](https://github.com/VsevolodCod/Linza-BI/issues/30), [#24](https://github.com/VsevolodCod/Linza-BI/issues/24), [#33](https://github.com/VsevolodCod/Linza-BI/issues/33) |
| [#35](https://github.com/VsevolodCod/Linza-BI/issues/35) | Качество: CI и приёмочная матрица девяти областей × шести сценариев | C | L | [#30](https://github.com/VsevolodCod/Linza-BI/issues/30), [#18](https://github.com/VsevolodCod/Linza-BI/issues/18), [#25](https://github.com/VsevolodCod/Linza-BI/issues/25), [#20](https://github.com/VsevolodCod/Linza-BI/issues/20), [#34](https://github.com/VsevolodCod/Linza-BI/issues/34) |
| [#36](https://github.com/VsevolodCod/Linza-BI/issues/36) | Финал: сценарий демонстрации, презентация и release checklist | C | M | [#35](https://github.com/VsevolodCod/Linza-BI/issues/35), [#14](https://github.com/VsevolodCod/Linza-BI/issues/14) |

## M3 · Дополнительные возможности — 4 задач

| Issue | Результат | Зона | Размер | Зависимости |
|---|---|---|---|---|
| [#37](https://github.com/VsevolodCod/Linza-BI/issues/37) | Дополнительно: сезонность и прогноз с временным backtest | B | L | [#25](https://github.com/VsevolodCod/Linza-BI/issues/25), [#26](https://github.com/VsevolodCod/Linza-BI/issues/26), [#14](https://github.com/VsevolodCod/Linza-BI/issues/14) |
| [#38](https://github.com/VsevolodCod/Linza-BI/issues/38) | Дополнительно: проверка гипотез и лагов без заявлений о причинности | B | L | [#25](https://github.com/VsevolodCod/Linza-BI/issues/25) |
| [#39](https://github.com/VsevolodCod/Linza-BI/issues/39) | Дополнительно: what-if с явными допущениями | B | M | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#26](https://github.com/VsevolodCod/Linza-BI/issues/26) |
| [#40](https://github.com/VsevolodCod/Linza-BI/issues/40) | Дополнительно: ClickHouse как второй прямой источник | B | M | [#23](https://github.com/VsevolodCod/Linza-BI/issues/23), [#35](https://github.com/VsevolodCod/Linza-BI/issues/35) |

## Покрытие требований

| Требование / сценарий | Задачи и доказательство |
|---|---|
| Исходные неизвестные CSV без внешней подготовки | [#5](https://github.com/VsevolodCod/Linza-BI/issues/5), [#7](https://github.com/VsevolodCod/Linza-BI/issues/7), [#8](https://github.com/VsevolodCod/Linza-BI/issues/8) — manifest, отчёт импорта и контрольные fixtures |
| Обзор неизвестных данных и содержательные ответы | [#22](https://github.com/VsevolodCod/Linza-BI/issues/22), [#12](https://github.com/VsevolodCod/Linza-BI/issues/12), [#13](https://github.com/VsevolodCod/Linza-BI/issues/13), [#11](https://github.com/VsevolodCod/Linza-BI/issues/11), [#14](https://github.com/VsevolodCod/Linza-BI/issues/14) |
| Прямое PostgreSQL или ClickHouse подключение | [#23](https://github.com/VsevolodCod/Linza-BI/issues/23), [#24](https://github.com/VsevolodCod/Linza-BI/issues/24) — изменение внешней БД видно после refresh; ClickHouse необязателен |
| Группировки, дубликаты, аномалии | [#19](https://github.com/VsevolodCod/Linza-BI/issues/19), [#21](https://github.com/VsevolodCod/Linza-BI/issues/21), [#25](https://github.com/VsevolodCod/Linza-BI/issues/25) — числовые эталоны |
| Графики в чате и смена представления | [#26](https://github.com/VsevolodCod/Linza-BI/issues/26), [#27](https://github.com/VsevolodCod/Linza-BI/issues/27) |
| Автоматический сохраняемый дашборд | [#28](https://github.com/VsevolodCod/Linza-BI/issues/28), [#29](https://github.com/VsevolodCod/Linza-BI/issues/29), [#30](https://github.com/VsevolodCod/Linza-BI/issues/30) — создать, перезапустить, открыть |
| Контекст диалога и независимые сессии | [#16](https://github.com/VsevolodCod/Linza-BI/issues/16), [#17](https://github.com/VsevolodCod/Linza-BI/issues/17), [#18](https://github.com/VsevolodCod/Linza-BI/issues/18) |
| Понятные ответы, уточнения и неверные вопросы | [#20](https://github.com/VsevolodCod/Linza-BI/issues/20), [#31](https://github.com/VsevolodCod/Linza-BI/issues/31), [#22](https://github.com/VsevolodCod/Linza-BI/issues/22) |
| Локальная модель, лицензии, автономность и ограничения сети | [#10](https://github.com/VsevolodCod/Linza-BI/issues/10), [#33](https://github.com/VsevolodCod/Linza-BI/issues/33), [#34](https://github.com/VsevolodCod/Linza-BI/issues/34) |
| Проверка всех сценариев и финальная защита | [#35](https://github.com/VsevolodCod/Linza-BI/issues/35), [#36](https://github.com/VsevolodCod/Linza-BI/issues/36) — release matrix и живой demo |

## Правила завершения

Каждая issue содержит результат, границы, критерии, способ проверки, зависимости, риск, относительный размер и DoD. Перед реализацией прочитать актуальное описание и комментарии. Работать в отдельной ветке `issue-N-...`; PR содержит `Closes #N`, фактические проверки и ограничения. Самостоятельно не сливать PR и не закрывать issue до merge. Сырые конкурсные данные, секреты и веса моделей не публиковать.

## Доска и ограничения проверки

Существующая доска №2 используется по указанию Всеволода. Публикация Issues, milestones и labels проверяется через GitHub API. Текущий CLI-токен не имеет project/read:project; проверить членство карточек и настроить представления Projects через него нельзя. Автоматическое добавление, о котором сообщил Всеволод, не выдаётся за проверенное действие. Все карточки доступны по прямым ссылкам и фильтрам Issues независимо от доски.

Рекомендуемые представления: Board по Status; таблица текущего milestone с Priority/Assignee; фильтры по `role:A/B/C`. Если автоматизация доски добавляет новые Issues, она должна подхватить опубликованные карточки. Проверка фактического переноса остаётся отдельным ограничением текущей сессии.
