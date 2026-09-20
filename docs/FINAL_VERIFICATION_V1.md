# Этап H — итоговая проверка и передача

Дата среза: 2026-09-20. Этот документ фиксирует только фактически выполненные
проверки текущего `main`. FastAPI/OpenAPI добавлены после исходного H-аудита;
полный браузерный E2E с backend/PostgreSQL всё ещё не объявляется выполненным.

## Результат проверки

| Контур | Результат | Что доказано |
|---|---:|---|
| Python lint/format | passed | `ruff check` и `ruff format --check` для репозитория |
| Python unit/integration без внешней БД | 181 passed, 6 skipped | Контракты, point-in-time данные, обучение, action fail-closed, сценарии, ranking, coordinator, CLI/FastAPI/OpenAPI |
| PostgreSQL 17 | 6 passed | Alembic с нуля/check, JSONB/TIMESTAMPTZ/FK, rollback, reconnect, save/history, конкурентный replay |
| Frontend unit/UI | 9 passed ранее; текущий повтор environment-blocked | У второго разработчика тесты прошли; локальный Node 20.18.1 не удовлетворяет требованию зафиксированных Vite/jsdom >=20.19.0, поэтому текущий Vitest не стартовал |
| Frontend type/build | passed | TypeScript typecheck и production Vite build; Vite при сборке также предупреждает обновить Node до >=20.19.0 |
| Contract drift | passed | Сгенерированный TypeScript совпадает с `examples/contract_v1.schema.json` |
| Данные | passed | `prepare`: dataset `sha256:733562b...a6a6c`, 18 354 049 telemetry rows, 301 904 analyses, 6 events |
| Модель | passed | `train`: persistence baseline, validation MAE 0.573082, test MAE 0.706412, прежняя version hash воспроизведена |
| Production composition A–E | passed | Реальный snapshot на `2026-08-06T21:00:00Z` → QualityAgent → Evaluator → Coordinator |
| HTTP/OpenAPI | passed без внешней БД | 11 routes, request validation, structured errors, readiness и checked-in OpenAPI покрыты HTTP-тестами |
| Browser → API → PostgreSQL | pending | Все части реализованы, но общий процесс с настоящей БД и браузером ещё не прогнан; fixture не считается E2E |

PostgreSQL проверялся на отдельном временном Compose project с PostgreSQL 17.
Fixture удалил только созданные им project/volume; SQLite и пользовательская БД
не использовались. `data/processed/` и `artifacts/` воспроизведены локально и
остаются Git-ignored.

## Покрытие обязательных сценариев

- Временная утечка: delayed LIMS, future measurement/range, backward as-of,
  purged temporal split и train-only action audit покрыты Python-тестами.
- Контракты: NaN/Inf, смешанные snapshot, schema/fixture round-trip и одинаковый
  feature builder train/inference проверены.
- Решения: неизвестные/запрещённые controls, диапазоны, шаги, комбинации,
  обязательный unknown check, недопустимый baseline, отсутствие допустимых
  вариантов, недостаток данных и hard-check bypass проверены.
- Равенство system/operator и возможность победы operator проверены одним
  evaluator path; throughput/unknown cost не компенсируют качество.
- Persistence: полный calculation rollback, immutable conflicts, save по
  server-side ID, история после reconnect и гонка expected_snapshot_id проверены
  на настоящем PostgreSQL.
- Frontend: late response для старого snapshot игнорируется даже если транспорт
  фактически завершил Promise; новый совет не смешивается со старым. История
  запрашивает полный Decision и его исходный snapshot. Ошибка API не отображается
  как `no_feasible_option`; `null` остаётся «не оценено»; график рисует только
  поддержанную прогнозную точку.

Real smoke после свежих `prepare/train` дал snapshot
`ec456123-367a-57d6-855f-d898f47a33fb`, supported baseline quality,
`baseline.admissibility=not_assessable`, Decision `no_feasible_option` и
`preferred=null`. Это ожидаемый fail-closed результат: реальные controls всё ещё
`available=false`, а неизвестная обязательная применимость не считается пройденной.

## Воспроизводимые команды

```bash
uv sync --frozen
uv run neftecode-hackathon prepare
uv run neftecode-hackathon train
uv run ruff check .
uv run ruff format --check .
uv run pytest
RUN_POSTGRES_TESTS=1 uv run pytest tests/test_postgres_preparation.py -q

cd frontend
npm ci
npm run check:contracts
npm run typecheck
npm test
npm run build
```

`RUN_POSTGRES_TESTS=1` требует работающий Docker. Обычный `pytest` намеренно
пропускает шесть opt-in PostgreSQL-тестов.

## Что остаётся до полной приёмки H

1. Выполнить один общий E2E: миграция → replay snapshot → Decision → operator
   action → save → history, затем тот же путь из браузера.
2. Зафиксировать реальные ответы достижимых статусов и HTTP 404/409/422/503 в E2E.
3. При необходимости добавить OpenAPI-codegen transport envelope для frontend;
   текущие изолированные типы уже сверены с опубликованной схемой.
4. Подготовить дополнительные демонстрационные эпизоды. Искусственно
   испорченный сценарий маркировать synthetic; реальные actions не открывать до
   появления подтверждённой action-support evidence.

До выполнения этих пунктов H имеет статус **частично выполнен / E2E pending**, а не
«готовый продукт». Прежний API-блокер снят; оставшаяся работа — проверка собранных частей
в одном запущенном окружении.
