# Этап H — итоговая проверка и передача

Дата среза: 2026-09-22. Этот документ фиксирует только фактически выполненные
проверки рабочего дерева поверх актуального `main`, включая общий браузерный E2E
с FastAPI и PostgreSQL.

## Результат проверки

| Контур | Результат | Что доказано |
|---|---:|---|
| Python lint/format | passed | `ruff check` и `ruff format --check` для репозитория |
| Python unit/integration без внешней БД | 181 passed, 6 skipped | Контракты, point-in-time данные, обучение, action fail-closed, сценарии, ranking, coordinator, CLI/FastAPI/OpenAPI |
| PostgreSQL 17 | 6 passed | Alembic с нуля/check, JSONB/TIMESTAMPTZ/FK, rollback, reconnect, save/history, конкурентный replay |
| Frontend unit/UI | 13 passed | Replay bootstrap, standalone evaluation, race/stale, history, график и ошибки API |
| Frontend type/build | passed | TypeScript typecheck и production Vite build на Node 24.19.0 |
| Contract drift | passed | Доменные типы совпадают с JSON Schema, transport-типы — с checked-in OpenAPI |
| Данные | passed | `prepare`: dataset `sha256:733562b...a6a6c`, 18 354 049 telemetry rows, 301 904 analyses, 6 events |
| Модель | passed | `train`: persistence baseline, validation MAE 0.573082, test MAE 0.706412, прежняя version hash воспроизведена |
| Production composition A–E | passed | Реальный snapshot на `2026-08-06T21:00:00Z` → QualityAgent → Evaluator → Coordinator |
| HTTP/OpenAPI | passed без внешней БД | 11 routes, request validation, structured errors, readiness и checked-in OpenAPI покрыты HTTP-тестами |
| Browser → API → PostgreSQL | passed | Fresh migration, replay start/advance, Decision, standalone scenario, save/history/stale и реальный экран |

Повторная приёмка разработчика 1 на актуальном `main` 2026-09-21 подтвердила:
экспорт JSON Schema/OpenAPI без содержательного drift, Ruff, `181 passed, 6 skipped`,
реальный CLI `evaluate`, frontend contract checks/typecheck, 13 тестов и production
build на Node 24.19.0. После восстановления повреждённых Docker runtime sockets
отдельный PostgreSQL 17 suite также повторно прошёл: 6/6 на временной БД.
Browser E2E ниже первоначально выполнил второй разработчик; 2026-09-22 первый
разработчик независимо повторил его на новой временной БД.

Финальная приёмка 2026-09-22 заново подняла отдельную чистую PostgreSQL 17,
выполнила Alembic upgrade/check и повторила полный HTTP/browser путь. UI сохранил
текущее решение, добавил его в историю и открыл прежний Decision вместе с его
исходным snapshot, корректно пометив расчёт устаревшим. Проверка консоли выявила
повторяющиеся React keys в одинаковых explanation/trace; дефект исправлен и
закрыт регрессионным UI-тестом. После исправления новых ошибок консоли нет.

PostgreSQL проверялся на отдельном временном Compose project с PostgreSQL 17.
Fixture удалил только созданные им project/volume; SQLite и пользовательская БД
не использовались. `data/processed/` и `artifacts/` воспроизведены локально и
остаются Git-ignored.

Общий E2E выполнен на отдельной свежей БД: health вернул готовность всех трёх
компонентов; episode `heldout-2026-08-06` создал replay snapshot; `/decisions`
вернул ожидаемый fail-closed `no_feasible_option`; `/scenarios/evaluate` —
`rejected`; save был идемпотентен, история прочиталась после записи, advance
создал новый snapshot, а сохранённый расчёт стал `stale=true`. Затем тот же
backend был открыт настоящим Vite-приложением в браузере: показаны реальные
snapshot, прогноз 7.55 мг/кг с интервалом 6.33–8.77, причины закрытых controls,
решение и история. Сохранение из UI и возврат к исходному snapshot проверены
отдельно. Fixture в этом прогоне не использовался.

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
  поддержанную прогнозную точку. Fresh DB автоматически запускает первый
  доступный episode. Отдельная проверка action использует `/scenarios/evaluate`
  и не заменяет выбранный Decision.

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

## Итог и внешние ограничения

Этап H для согласованной v1 завершён: код, HTTP, PostgreSQL и браузер проверены
единым путём. Подготовка нескольких дополнительных демонстрационных эпизодов
остаётся улучшением презентации, а не разрывом интеграции.

Реальные изменения P8/T11/F19 намеренно остаются закрыты. Для их активации нужны
внешние подтверждения единиц/шкал, допустимых train-диапазонов и шага, joint
action support, counterfactual uncertainty и переходного отклика. Пока этих
данных нет, честный продуктовый результат — `no_feasible_option`, а не
синтетическая рекомендация. Это единственный существенный предметный вход,
которого не хватает для советов с реальными воздействиями.
