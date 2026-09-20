# Neftecode Hackathon

Python-проект для хакатона, управляемый через [uv](https://docs.astral.sh/uv/).

## Быстрый старт

```bash
uv sync
uv run pre-commit install
uv run neftecode-hackathon prepare
uv run neftecode-hackathon train
uv run neftecode-hackathon evaluate --at 2026-08-06T21:00:00Z
```

Команда `prepare` читает неизменяемые исходники из `context/` и создаёт локальные
Parquet/JSON-артефакты в `data/processed/`. Этот каталог исключён из Git. Форматы,
проверки качества и допущения описаны в [docs/DATA_PREPARATION.md](docs/DATA_PREPARATION.md).
Команда `train` воспроизводимо обучает и проверяет прогноз продолжения на 60 минут,
сохраняя локальные артефакты в исключённом из Git каталоге `artifacts/`. Методика и
фактические метрики: [docs/FORECAST_MODEL_V1.md](docs/FORECAST_MODEL_V1.md).
Проверка применимости управляющих действий и причины их текущей блокировки:
[docs/ACTION_ASSESSMENT_V1.md](docs/ACTION_ASSESSMENT_V1.md).
Экран советчика, его проверенные команды и интеграция с FastAPI:
[docs/FRONTEND_V1.md](docs/FRONTEND_V1.md).
Итоговая матрица H с фактически пройденными проверками и оставшимся полным E2E:
[docs/FINAL_VERIFICATION_V1.md](docs/FINAL_VERIFICATION_V1.md).
Матрица передач между разработчиками и список следующих незакрытых этапов:
[docs/INTEGRATION_AUDIT_A_E.md](docs/INTEGRATION_AUDIT_A_E.md).

## PostgreSQL и API

После `prepare` и `train` создайте локальный `.env` по `.env.example`, замените пароль
и передайте `DATABASE_URL` процессам Alembic и backend. Секреты не коммитятся.

```bash
docker compose up -d --wait
uv run alembic upgrade head
uv run neftecode-hackathon serve
```

Backend доступен только локально: `http://127.0.0.1:8000`. Проверка готовности —
`GET /api/v1/health`, интерактивный OpenAPI — `/docs`. Без данных, модели или PostgreSQL
health возвращает `ready=false`, а рабочие методы — понятный 503 без тестовой подмены.
Полный HTTP-контракт, replay и порядок запуска: [docs/API_V1.md](docs/API_V1.md).
Статический OpenAPI для frontend: [examples/openapi.v1.json](examples/openapi.v1.json).

Frontend находится в `frontend/` и в dev-режиме проксирует `/api` на локальный FastAPI.

Исходные временные метки интерпретируются как `Europe/Moscow` и сохраняются в UTC.
Для ЛИМС используется консервативная доступность через 240 минут после отбора пробы;
120 минут остаются только экспериментальной sensitivity-проверкой. Это модель replay,
а не фактическое время готовности каждой лабораторной пробы.

## Проверки для разработки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pre-commit run --all-files
```

Frontend проверяется отдельно:

Требуется Node.js >=20.19.0 (или >=22.12.0), как требует зафиксированный Vite 7.

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

Реальный API-режим включён по умолчанию и ожидает `/api/v1`. Явно включаемый
synthetic preview через `VITE_USE_FIXTURE=true` помечен в интерфейсе и не имитирует
расчёт пользовательских воздействий.

Автоматически исправить lint-ошибки и отформатировать код:

```bash
uv run ruff check --fix .
uv run ruff format .
```
