# Интеграционный аудит этапов A–E

Срез на 2026-09-16. Документ проверяет передачи между двумя маршрутами по текущему коду,
конфигурации, тестам и локальному real smoke. Он не заменяет исходные планы в handoff.

## Матрица выполнения

| Зависимость | Передача | Статус | Проверяемое основание |
| --- | --- | --- | --- |
| Общие контракты | разработчик 1 → 2 | Выполнено | Один `contracts.py`, общий fixture/Schema; scenarios/orchestration используют эти типы |
| QualityAgent DI | разработчик 1 → 2 | Выполнено | `ScenarioEvaluator` принимает общий protocol; production не импортирует test doubles |
| Каталог управлений | совместно | Выполнено fail-closed | Смысл P8/T11/F19 подтверждён; единицы/шкалы не подтверждены, поэтому все `available=false` |
| Подготовленные данные | разработчик 1 → 2 | Выполнено | `prepare` воспроизводит Parquet/JSON и dataset version; source files не меняются |
| Реальный snapshot | разработчик 1 → 2 | Выполнено | Point-in-time `SnapshotProvider`, freshness, delayed LIMS, immutable ID |
| Проверки сценариев | разработчик 2 → 1 | Выполнено | Pre/post-model checks, единый evaluator, неизвестная обязательная проверка блокирует |
| Continuation forecast | разработчик 1 → 2 | Выполнено | Train/validation/test, persistence победил HGB, empirical interval, replay boundary |
| Severity/эффективность | разработчик 2 → 1 | Выполнено fail-closed | Формулы/DI готовы; реальные числа не выдаются без единиц, нормировок и response model |
| Кандидаты/ранжирование | разработчик 2 → 1 | Выполнено | Один evaluator, до 27+operator, hard feasibility, tolerances, четыре исхода |
| Action assessment | разработчик 1 → 2 | Выполнено fail-closed | Train-only action audit; нет unit/hold/joint-support/effect uncertainty/transition evidence |
| Coordinator/explanation | разработчик 2 → 1 | Выполнено | Baseline first, единый path, фактические explanations и trace без вымышленных чисел |
| Реальная композиция A–E | совместно | Выполнено | Snapshot → QualityAgent → Evaluator → Coordinator smoke на реальных локальных артефактах |

`Выполнено fail-closed` означает, что механизм и проверка реализованы, но продукт намеренно
не выдаёт численный результат без обязательных исходных подтверждений. Это соответствует
плану и безопаснее вымышленной активации.

## Согласованность версий

- Dataset: `sha256:733562b101af66617f6d3c1fae77e1106ad9b02a0c529c0f721c812801ce6a6c`.
- Model: `forecast-v1:cc3ac51f6ded1960700f3893e7bc0c7c91224cf3cf05eac09646d45fb60a4365`.
- Constraints: `controls-v1-action-readiness-20260916`.
- Model version в `artifacts/manifest.json` совпадает с `config/constraints.yaml`.
- Constraint version одинакова в `config/controls.yaml` и `config/constraints.yaml`.
- Список action controls в `config/model.yaml` совпадает с каталогом сценариев.
- Общий раздел двух handoff совпадает полностью.

## Фактический сквозной результат

Для snapshot `2026-08-06T21:00:00Z`:

- completeness = 1.0;
- baseline quality = `supported`;
- baseline evaluation = `not_assessable`, потому что interval policy и hard-check inventory
  не утверждены;
- прямой action P8 = `unsupported` без prediction/lower/upper;
- тот же action через evaluator = `rejected` на `controls.unavailable.ht:P8`;
- Decision = `no_feasible_option`, preferred = null.

Такой результат целостен: отсутствие подтверждений не превращается в `no_change`, допустимый
сценарий или рекомендацию.

## Что не потеряно, но относится к следующим этапам

| Работа | Владелец/этап | Текущее состояние |
| --- | --- | --- |
| Replay repository и transactional advance | разработчик 2, F | Выполнено после аудита A–E; expected_snapshot_id и гонка двух Session проверены |
| Полная persistence-транзакция решения и evaluations | разработчик 2, F | Выполнено после аудита A–E; atomic rollback/save/history проверены, API-flow ещё не подключён |
| `evaluate` и `serve`, FastAPI/OpenAPI | разработчик 1, F | Не реализовано; `prepare` и `train` готовы |
| PostgreSQL E2E после API | совместно F/H | Предыдущая отдельная БД проверена; новый API E2E ещё впереди |
| React и защита от stale responses | разработчик 2, G | Не реализовано |
| Демо полезного изменения | совместно | Заблокировано отсутствием защищаемого action effect; не заменяется synthetic результатом |

Developer 2 F persistence/replay завершён. Следующий корректный порядок: developer 1 F
CLI/FastAPI подключает repositories, затем интеграционный PostgreSQL E2E,
OpenAPI → frontend G и финальные проверки.

## Проверки аудита

- `uv run ruff check .`
- `uv run ruff format --check .`
- После F `uv run pytest`: 174 passed, 6 skipped; пропущены только opt-in PostgreSQL tests.
- После F отдельный PostgreSQL 17: 6 passed; временный Compose project/volume удалён.
- Два последовательных запуска `train` дали одинаковую model version и одинаковые метрики.
- `git diff --check` прошёл; производные data/artifacts остаются Git-ignored.
