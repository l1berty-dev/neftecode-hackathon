# Этап H — итоговая проверка и передача

Дата среза: 2026-09-20. Этот документ фиксирует только фактически выполненные
проверки текущего `main`. Он не объявляет готовыми отсутствующие FastAPI routes,
OpenAPI или браузерный E2E с backend.

## Результат проверки

| Контур | Результат | Что доказано |
|---|---:|---|
| Python lint/format | passed | `ruff check` и `ruff format --check` для репозитория |
| Python unit/integration без внешней БД | 174 passed, 6 skipped | Контракты, point-in-time данные, обучение, action fail-closed, сценарии, ranking, coordinator |
| PostgreSQL 17 | 6 passed | Alembic с нуля/check, JSONB/TIMESTAMPTZ/FK, rollback, reconnect, save/history, конкурентный replay |
| Frontend unit/UI | 9 passed | Ошибка API отдельно от бизнес-отказа, unknown, save ID, исходный snapshot истории, прогноз без вымышленной линии, stale race |
| Frontend type/build | passed | TypeScript typecheck и production Vite build |
| Contract drift | passed | Сгенерированный TypeScript совпадает с `examples/contract_v1.schema.json` |
| Данные | passed | `prepare`: dataset `sha256:733562b...a6a6c`, 18 354 049 telemetry rows, 301 904 analyses, 6 events |
| Модель | passed | `train`: persistence baseline, validation MAE 0.573082, test MAE 0.706412, прежняя version hash воспроизведена |
| Production composition A–E | passed | Реальный snapshot на `2026-08-06T21:00:00Z` → QualityAgent → Evaluator → Coordinator |
| HTTP/OpenAPI E2E | blocked | В репозитории отсутствуют FastAPI routes, `serve`, OpenAPI и HTTP-тесты |
| Browser → API → PostgreSQL | blocked | Нельзя проверять без предыдущего пункта; fixture не считается E2E |

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

## Что должен завершить разработчик 1 до полной приёмки H

1. Реализовать CLI `evaluate`/`serve` и все routes общего HTTP-контракта через
   существующие Coordinator и repositories, без параллельной бизнес-логики.
2. Экспортировать актуальный OpenAPI и добавить HTTP-тесты 404/409/422/503,
   snapshot/horizon/stale и четырёх DecisionStatus.
3. Передать реальные response fixtures. Разработчик 2 заменит временные transport
   envelopes frontend генерацией из OpenAPI.
4. Выполнить один общий E2E: миграция → replay snapshot → Decision → operator
   action → save → history, затем тот же путь из браузера.
5. Подготовить несколько изменяемых демонстрационных эпизодов. Искусственно
   испорченный сценарий маркировать synthetic; реальные actions не открывать до
   появления подтверждённой action-support evidence.

До выполнения этих пунктов H имеет статус **частично выполнен / integration
blocked**, а не «готовый продукт». Блокер находится в отсутствующем API, а не в
PostgreSQL, frontend или чистом расчётном цикле.
