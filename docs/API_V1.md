# CLI и HTTP API v1

## Назначение и границы

Backend предоставляет один расчётный путь для CLI и FastAPI: `SnapshotProvider` →
`ForecastQualityAgent` → `ScenarioEvaluator` → `Coordinator`. HTTP не обучает модель,
не принимает пути к файлам и не исполняет команды на оборудовании. Данные подаются только
как ускоренное воспроизведение истории.

Модель, конфигурации и каталог эпизодов загружаются один раз при старте процесса. Синхронные
FastAPI handlers выполняются в worker thread и не блокируют event loop. Локальный прототип
запускается с одним API-worker, потому что replay использует единый курсор.

## CLI

```bash
uv run neftecode-hackathon prepare
uv run neftecode-hackathon train
uv run neftecode-hackathon evaluate --at 2026-08-06T21:00:00Z
uv run neftecode-hackathon serve
```

`evaluate` не требует PostgreSQL и печатает полный `Decision` для указанного replay-времени.
Метка времени обязана содержать offset. `serve` слушает только `127.0.0.1`, порт берётся из
`API_PORT` (по умолчанию 8000).

## Запуск API с PostgreSQL

1. Выполнить `prepare` и `train`.
2. Создать локальный `.env` по `.env.example`, заменив пароль; секрет не коммитить.
3. Запустить `docker compose up -d --wait`.
4. Передать тот же `DATABASE_URL` процессам Alembic и backend, например через
   `uv run --env-file .env ...`; один только файл `.env` Python автоматически не читает.
5. Выполнить `uv run --env-file .env alembic upgrade head` и
   `uv run --env-file .env neftecode-hackathon serve`.
6. Проверить `GET http://127.0.0.1:8000/api/v1/health`.

Без подготовленных данных, модели или БД health остаётся доступен, но `ready=false`; рабочие
маршруты возвращают 503 без синтетической подмены. `DATA_DIR` и `MODEL_DIR` можно задать через
окружение процесса. Браузер не может передать произвольный путь.

## HTTP-контракт

Префикс: `/api/v1`. Интерактивная документация: `/docs`; OpenAPI: `/openapi.json`.
Проверенная статическая передача frontend: `examples/openapi.v1.json`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Готовность данных, модели и PostgreSQL без секретов |
| GET | `/controls` | Версия и полный каталог управлений, включая причины недоступности |
| GET | `/episodes` | Реальные replay-эпизоды и ограничения |
| POST | `/replay/start` | Начать эпизод и атомарно сохранить первый snapshot |
| POST | `/replay/advance` | Перейти на 10 минут при совпавшем `expected_snapshot_id` |
| GET | `/snapshots/current` | Текущий неизменяемый snapshot |
| GET | `/snapshots/{id}` | Snapshot по ID |
| POST | `/decisions` | Полный расчёт Coordinator; вариант оператора передаёт только `changes` |
| POST | `/scenarios/evaluate` | Отдельная оценка операторского действия |
| POST | `/decisions/{id}/save` | Идемпотентно отметить серверный расчёт сохранённым |
| GET | `/decisions` | Краткая история, по умолчанию только сохранённые решения |
| GET | `/decisions/{id}` | Полный расчёт и актуальный `stale` |

Некорректный JSON, неизвестное управление, NaN/Inf, лишнее поле и горизонт не 60 минут дают
422. Отсутствующий ID даёт 404. Несовпавший replay cursor — 409 с актуальным snapshot ID.
Бизнес-отказы (`rejected`, `insufficient_data`, `no_feasible_option`) возвращаются как 200.
Ошибки имеют единый объект `{code, message, details}` и не содержат SQL/credentials.

## Текущее поведение исходов

На реальных артефактах текущая политика даёт `no_feasible_option`: continuation forecast
работает, но обязательные hard checks не утверждены, а P8/T11/F19 закрыты fail-closed аудитом.
Это нормальный честный ответ. `change_recommended` и `no_change` нельзя показывать как реальные,
пока controls недоступны; они покрыты контрактом и synthetic unit-тестами Coordinator.
`insufficient_data` возникает при недоступном обязательном входе, но не подстраивается специально
в выбранном демонстрационном эпизоде.

## Обновление и проверки

```bash
uv run python scripts/export_openapi.py
uv run pytest tests/test_api.py tests/test_main.py
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

PostgreSQL-проверки opt-in и используют отдельный случайно именованный Compose-проект:

```bash
RUN_POSTGRES_TESTS=1 uv run pytest tests/test_postgres_preparation.py
```
