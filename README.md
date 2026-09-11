# Neftecode Hackathon

Python-проект для хакатона, управляемый через [uv](https://docs.astral.sh/uv/).

## Быстрый старт

```bash
uv sync
uv run pre-commit install
uv run neftecode-hackathon prepare
```

Команда `prepare` читает неизменяемые исходники из `context/` и создаёт локальные
Parquet/JSON-артефакты в `data/processed/`. Этот каталог исключён из Git. Форматы,
проверки качества и допущения описаны в [docs/DATA_PREPARATION.md](docs/DATA_PREPARATION.md).

Исходные временные метки интерпретируются как `Europe/Moscow` и сохраняются в UTC.
Нулевая задержка доступности источников и отдельная чувствительность ЛИМС 120 минут —
экспериментальные допущения, а не подтверждённые характеристики промышленной системы.

## Проверки для разработки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pre-commit run --all-files
```

Автоматически исправить lint-ошибки и отформатировать код:

```bash
uv run ruff check --fix .
uv run ruff format .
```
