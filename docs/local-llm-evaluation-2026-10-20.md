# Локальные модели и CSV → SQL — 20 октября 2026

> Исторический отчёт от 20.10.2026. Он сравнивает только два вопроса и не
> используется для выбора модели после появления `evals/v1`. Для актуального
> сравнения используйте `python -m scripts.benchmark_local_models` из README:
> новый runner считает EX по данным, валидность JSON/SQL, ошибки и cold/warm
> latency на 20 versioned cases.

Стенд: Apple M4, 16 GiB unified memory, macOS 26.5, Ollama 0.40.6. Все запросы шли к `http://127.0.0.1:11434`; для сравнения использовался один и тот же провайдер `OllamaProvider`, контекст исполнения 4096 токенов, `THINKING=0`, `MAX_TOKENS_G=256`, `TIMEOUT=120`. Веса моделей, данные пользователя и секреты в git не входят.

| Модель | Digest (Ollama) | Размер / quantization | Контекст модели | Лицензия в пакете |
| --- | --- | --- | --- | --- |
| `qwen2.5-coder:7b` | `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | 4.7 GB / Q4_K_M | 32 768 | Apache 2.0 |
| `qwen2.5-coder:3b` | `f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225` | 1.9 GB / Q4_K_M | 32 768 | Qwen Research License; только некоммерческое использование |
| `llama3.2:3b` | `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72` | 2.0 GB / Q4_K_M | 131 072 | Llama 3.2 Community License |

После подготовки весов Ollama был перезапущен с `OLLAMA_NO_CLOUD=true`; сервер подтвердил `Ollama cloud disabled: true`. На одинаковых двух вопросах из синтетического CSV (`COUNT(*)`, `SUM(revenue)`):

| Модель | Правильных ответов | Время двух ответов | `size_vram` после запроса | Вывод |
| --- | --- | --- | --- | --- |
| Qwen 7B | 2/2 | 2.8 и 3.4 с; повторно 4.0 и 4.1 с | 4.65 GB | Выбран для локальной интеграции |
| Qwen 3B | 2/2 | 4.6 с с загрузкой и 1.9 с | 2.09 GB | Быстрее после прогрева, но исследовательская лицензия |
| Llama 3B | 1/2 | 8.1 с с загрузкой и 2.1 с | 2.34 GB | Не прошёл вопрос о сумме после разрешённого исправления |

В повторном прогоне RSS процесса Qwen 7B составил 1.2 GiB; это не полный расход общей памяти с GPU-страницами. На Apple Silicon `size_vram` относится к общей памяти, а не к отдельной видеопамяти. Единичные времена и два вопроса не являются достаточным бенчмарком качества на произвольных данных. JSON Schema передаётся в `format`, а ответ дополнительно валидируется Pydantic. Тесты покрывают malformed JSON, недоступную модель и таймаут; SQL проверяется отдельным read-only исполнителем.

Для повторения установите Ollama, скачайте указанные теги и запустите сервер локально. После скачивания можно отключить облачный режим Ollama:

```sh
ollama pull qwen2.5-coder:3b
ollama pull llama3.2:3b
ollama pull qwen2.5-coder:7b
OLLAMA_NO_CLOUD=true ollama serve
python -m scripts.verify_local_models qwen2.5-coder:7b qwen2.5-coder:3b llama3.2:3b --output /tmp/evia-local-model-report.json
```

Скрипт загружает только встроенный синтетический CSV (`month,revenue`) и прогоняет одинаковые вопросы на каждом теге. Он выводит digest, quantization, лицензию, результат SQL, время и память запущенной модели. Для проверки сервера с выбранным тегом задайте `LLM_PROVIDER=ollama`, `LLM_MODEL=<точный тег>` и запустите `python -m scripts.run` после сборки frontend. В браузере загрузите небольшой CSV, выберите его и спросите «Сколько всего выручки?»; на вкладке результата должны быть метка «Рассчитано по CSV», SQL и таблица с числом из `QueryResult`. При `LLM_PROVIDER=mock` отображается «Демо-ответ».

Прямое подключение Railway к Ollama на ноутбуке не возникает автоматически: развернутому сервису нужен доступный из его сети inference endpoint. Поэтому локальная приёмка не означает, что публичный Railway-сайт уже использует эту модель.

Сведения о тегах и лицензиях можно сверить с [реестром Qwen 7B](https://ollama.com/library/qwen2.5-coder:7b), [лицензией исходного Qwen 7B](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct/blob/main/LICENSE), [реестром Qwen 3B](https://ollama.com/library/qwen2.5-coder:3b) и [реестром Llama 3.2](https://ollama.com/library/llama3.2:3b). Для этого отчёта лицензии также прочитаны из реально скачанных пакетов командой `ollama show <tag> --license`.
