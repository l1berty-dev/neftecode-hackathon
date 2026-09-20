# Этап F разработчика 2: PostgreSQL, repositories и replay

Срез 2026-09-20. Этап F завершён на существующей схеме Alembic `0001`:
новая миграция не потребовалась, потому что snapshots, decisions,
scenario_evaluations и единственная строка replay_state уже были созданы.
Проверка выполнялась только на отдельном временном PostgreSQL 17; SQLite не
использовался. Пользовательская БД и история не очищались.

## Границы ответственности

Чистые расчёты не обращаются к БД. Persistence получает и возвращает общие
`ProcessSnapshot` и `Decision` из `contracts.py`; для replay используется
внутренний immutable `ReplayPosition`, поскольку публичного API-контракта replay
пока нет. Payload хранится полностью в JSONB, а поля для FK/поиска — отдельно.

- `SnapshotRepository.put/get`: immutable snapshot с UUID, TIMESTAMPTZ,
  mode/dataset_version и полным JSONB.
- `DecisionRepository.put/get/list/save`: immutable calculation, все связанные
  evaluations, история saved decisions и идемпотентный `saved_at`.
- `CalculationRepository.record`: snapshot + decision + уникальные evaluations
  одной транзакцией; при ошибке не остаётся частичного DecisionRow.
- `CalculationRepository.save`: принимает server-side decision_id и в собственной
  транзакции повторно возвращает исходный `saved_at`.
- `ReplayRepository.initialize/get/advance/restart`: фиксированная строка id=1,
  episode_id, snapshot FK и position; caller владеет транзакцией replay-команды.

Низкоуровневые SnapshotRepository/DecisionRepository работают в транзакции
вызывающего кода. Для полного сохранения API использует CalculationRepository
на свежем Session. Метод отвергает уже начатую неявную транзакцию, чтобы граница
commit/rollback не оказалась скрытой или двойной.

## Неизменяемость и целостность

Повторный put того же ID и payload идемпотентен. Тот же UUID с другим
snapshot/decision/evaluation payload вызывает ValueError. Для evaluations
сверяются snapshot_id, decision_id и action. Decision validator до БД требует
общие snapshot/horizon/model/constraint version.

При чтении repository валидирует JSONB общим контрактом и сверяет его с
индексируемыми колонками: ID, snapshot_id, as_of, mode, dataset/status, horizon
и версиями. Рассогласование SQL-колонки и payload не принимается как история.
Это runtime detection, не DB trigger: прямые внешние SQL-записи запрещены.

FK блокируют решение без snapshot и replay на отсутствующий snapshot.
TIMESTAMPTZ round-trip проверен. Запросы построены SQLAlchemy и параметризованы.
Секрет читается из DATABASE_URL окружения; `.env.example` — только шаблон.

Downgrade `0001` намеренно не удаляет таблицы. F не добавляет destructive reset
пользовательской истории. Будущие изменения схемы выполняются новой Alembic
migration, не `create_all`.

## Replay и конкурентность

До initialize snapshots сохраняются. Повтор initialize с тем же episode,
snapshot и position идемпотентен; иная точка при существующей сессии даёт
`ReplayConflictError`. `advance(episode_id, expected_snapshot_id,
next_snapshot_id)` — один условный UPDATE:

```text
WHERE id=1 AND episode_id=:episode AND current_snapshot_id=:expected
SET current_snapshot_id=:next, position=position+1
```

Если другой запрос продвинул replay, affected row отсутствует и stale-запрос
получает ReplayConflictError: он не пропускает следующее состояние. Тест открывает
две независимые Session: обе читают позицию, вторая фиксирует advance, первая
конфликтует. Итоговая позиция увеличена ровно на один.

`restart` требует expected current snapshot, меняет episode, первый snapshot и
position=0. Неверный episode/expected snapshot конфликтует; неизвестный next
snapshot нарушает FK. API позже преобразует конфликт в HTTP conflict и возвращает
актуальное состояние, а не повторяет advance вслепую.

## Применение из API

```python
from sqlalchemy.orm import Session

from neftecode_hackathon.persistence import CalculationRepository, ReplayRepository

# engine создаётся приложением из DATABASE_URL; decision рассчитан сервером.
with Session(engine) as session:
    CalculationRepository(session).record(snapshot, decision)

# Клиент передаёт только server-side decision_id.
with Session(engine) as session:
    saved_at = CalculationRepository(session).save(decision.decision_id)

with Session(engine) as session, session.begin():
    position = ReplayRepository(session).advance(episode_id, expected_snapshot_id, next_snapshot_id)
```

Не принимать от клиента payload Decision/агентов для save. Не имитировать
сохранение в browser storage при недоступной БД. История решения открывается с
его snapshot_id, а не с текущим replay state.

## Выполненные проверки

Обычный прогон:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Результат: 174 passed, 6 skipped. Все skipped — opt-in PostgreSQL-тесты.

Изолированный PostgreSQL 17:

```sh
RUN_POSTGRES_TESTS=1 uv run pytest tests/test_postgres_preparation.py -q
```

Результат: 6 passed. Fixture создаёт случайный Compose project, пароль,
ephemeral port/volume, выполняет `alembic upgrade head` и `alembic check`, затем
удаляет только этот project и volume.

Проверены миграция с нуля, JSONB/TIMESTAMPTZ/FK, reconnect, immutable conflicts,
атомарный rollback, идемпотентный save/history list, replay initialize/advance/
restart, stale expected_snapshot_id двух Session, episode/FK conflicts и отказ
при рассогласовании структурированной колонки с JSONB payload.

На этапе H `prepare/train` и production composition A–E повторно прошли, а
PostgreSQL 17 тесты снова дали 6 passed. Frontend G и FastAPI/OpenAPI реализованы;
backend использует CalculationRepository и ReplayRepository без копирования транзакционной
логики. Полный browser/API/PostgreSQL E2E ещё не выполнен. Актуальная матрица:
[FINAL_VERIFICATION_V1.md](FINAL_VERIFICATION_V1.md).
