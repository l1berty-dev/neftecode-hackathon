# Neftecode Hackathon

Python-проект для хакатона, управляемый через [uv](https://docs.astral.sh/uv/).

## Быстрый старт

```bash
uv sync
uv run pre-commit install
uv run neftecode-hackathon
```

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
