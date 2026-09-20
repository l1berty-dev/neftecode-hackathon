# Neftecode Hackathon

Python-проект для хакатона, управляемый через [uv](https://docs.astral.sh/uv/).

## Быстрый старт

```bash
uv sync
uv run pre-commit install
uv run neftecode-hackathon prepare
uv run neftecode-hackathon train
```

Команда `prepare` читает неизменяемые исходники из `context/` и создаёт локальные
Parquet/JSON-артефакты в `data/processed/`. Этот каталог исключён из Git. Форматы,
проверки качества и допущения описаны в [docs/DATA_PREPARATION.md](docs/DATA_PREPARATION.md).
Команда `train` воспроизводимо обучает и проверяет прогноз продолжения на 60 минут,
сохраняя локальные артефакты в исключённом из Git каталоге `artifacts/`. Методика и
фактические метрики: [docs/FORECAST_MODEL_V1.md](docs/FORECAST_MODEL_V1.md).
Проверка применимости управляющих действий и причины их текущей блокировки:
[docs/ACTION_ASSESSMENT_V1.md](docs/ACTION_ASSESSMENT_V1.md).
Экран советчика, его проверенные команды и граница интеграции с ещё не реализованным
FastAPI: [docs/FRONTEND_V1.md](docs/FRONTEND_V1.md).
Итоговая матрица H с фактически пройденными проверками и оставшимся API-блокером:
[docs/FINAL_VERIFICATION_V1.md](docs/FINAL_VERIFICATION_V1.md).
Матрица передач между разработчиками и список следующих незакрытых этапов:
[docs/INTEGRATION_AUDIT_A_E.md](docs/INTEGRATION_AUDIT_A_E.md).

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

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

Реальный API-режим включён по умолчанию и ожидает `/api/v1`. До появления FastAPI
доступен только явно включаемый synthetic preview через `VITE_USE_FIXTURE=true`;
он помечен в интерфейсе и не имитирует расчёт пользовательских воздействий.

Автоматически исправить lint-ошибки и отформатировать код:

```bash
uv run ruff check --fix .
uv run ruff format .
```
