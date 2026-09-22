# Neftecode Advisor

## Начало

Neftecode Advisor — воспроизводимый советчик оператору для цепочки «АВТ →
гидроочистка → блендинг». Репозиторий содержит весь код, dashboard, отчёт и
презентацию; notebook и отдельный архив не нужны.

```bash
./scripts/demo.sh up
```

Первый запуск готовит 18,3 млн строк телеметрии, обучает две модели, применяет
миграции и обычно занимает 2–5 минут. Затем откройте
[Dashboard](http://127.0.0.1:8080). Для остановки: `./scripts/demo.sh down` —
контейнеры удалятся, локальные volumes с данными и моделями останутся.

Пять минут проверки:

1. Откройте стартовую вкладку «Модельные сценарии».
2. Выберите «Рост серы прямогонного ДТ» и нажмите «Рассчитать цепочку».
3. Проверьте цепочку «причина → действие → прогноз → рецепт → ограничения».
4. Выберите «Вариант оператора»: он оценивается тем же кодом и может победить.
5. Перейдите на вкладку «Исторический replay»: там сохранена честная fail-closed логика.

[Презентация PPTX](docs/presentation/Neftecode_Advisor.pptx) ·
[Презентация PDF](docs/presentation/Neftecode_Advisor.pdf) ·
[Результаты](docs/RESULTS.md) ·
[Методика](docs/MODELLED_CHAIN.md) ·
[Ограничения](docs/RESULTS.md#ограничения-и-честная-интерпретация) ·
[OpenAPI](examples/openapi.v1.json)

## Что демонстрировать

| Пресет | Ожидаемый исход | Что видно |
|---|---|---|
| Стабильный K5 | `no_change` | система не меняет режим ради шума |
| Рост серы прямогонного ДТ | `change_recommended` | компенсирующий режим P8/T11/F19 |
| Вариант оператора | `change_recommended` | операторский вариант побеждает системный |
| Нет свежих данных | `insufficient_data` | старый/отсутствующий факт не подменяется числом |
| Блендинг и 2-EHN | `no_change` | рецепт проходит серу, T95 и консервативный цетановый предел |

Все поля пресета редактируемы; ответ пересчитывается из текущего ввода и автоматически
сохраняется в PostgreSQL. Исторические решения и модельные расчёты хранятся раздельно.

## Результаты в цифрах

Исторический прогноз серы на +60 минут выбран на validation против learned-модели.
Победил persistence baseline: validation MAE 0,573 мг/кг (`n=28 440`), test MAE
0,706 мг/кг (`n=28 447`), test coverage q90-интервала 81,9%. Это мониторинг
продолжения процесса, а не оценка вмешательства.

Отдельный sign-constrained response audit для горизонта 180 минут выбрал лаг 60 минут
и Ridge α=10: validation MAE 1,153 мг/кг (`n=2 456`), test MAE 2,122 мг/кг
(`n=4 458`). Коэффициенты P8/T11/F19 на выданной истории обнулились ограничением;
поэтому величины эффекта в modelled what-if явно заданы как экспериментальные
допущения, а train p5–p95, лаг и q90 калибруются отдельно. Полные таблицы — в
[docs/RESULTS.md](docs/RESULTS.md).

## Архитектура

```text
context → prepare → Parquet → train / modelled-train
                              ↓
React/nginx → FastAPI → modelled chain → PostgreSQL JSONB
                    ↘ historical replay → Decision JSONB
```

- АВТ: исправленные формулы VAK организаторов с проверкой отсутствующих входов и нуля.
- Гидроочистка: отдельные historical forecast (+60 минут) и modelled response (+180 минут).
- Блендинг: сетка долей 5%, массовый баланс серы/цетана, линейный T95 proxy,
  консервативный эффект 2-EHN.
- Ограничения качества проверяются до cost/severity/throughput proxy.
- `contracts.py` — единственный доменный контракт; OpenAPI и TypeScript генерируются из него.
- Ни один режим не исполняет команды на оборудовании.

## Ручной запуск для разработки

Требуются Python 3.14, `uv`, Node.js 24+ и PostgreSQL 17.

```bash
uv sync --frozen
uv run neftecode-hackathon prepare
uv run neftecode-hackathon train
uv run neftecode-hackathon modelled-train
cp .env.example .env
docker compose up -d --wait
uv run --env-file .env alembic upgrade head
uv run --env-file .env neftecode-hackathon serve
```

Во втором терминале:

```bash
cd frontend
npm ci
npm run dev
```

## Проверки

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend
npm test
npm run typecheck
npm run build
npm run e2e       # при поднятом demo-стеке; сохраняет реальные screenshots
```

PostgreSQL opt-in suite запускается с `TEST_DATABASE_URL`. Схемы обновляются командой
`uv run python scripts/export_contract_schema.py`, затем `npm run generate:contracts`.

## Структура

| Путь | Назначение |
|---|---|
| `src/neftecode_hackathon/modelled/` | VAK, response audit, full-chain engine, blending |
| `src/neftecode_hackathon/quality/` | historical forecast и защита от утечки |
| `src/neftecode_hackathon/api/` | FastAPI и application service |
| `src/neftecode_hackathon/persistence/` | PostgreSQL repositories |
| `frontend/` | React dashboard и browser E2E |
| `config/modelled.yaml` | версии, train p5–p95 и видимые допущения |
| `docs/` | методика, результаты, презентация, handoff |
| `data/processed/`, `artifacts/` | локальные производные, не Git |

## Troubleshooting

- `Cannot connect to Docker daemon`: запустите Docker Desktop и повторите `demo.sh up`.
- Порт 8080 занят: остановите использующий его процесс; публичный порт намеренно локальный.
- Bootstrap завершился ошибкой: `./scripts/demo.sh logs`; исходники `context/` должны
  быть получены через Git LFS.
- Health не готов: `curl http://127.0.0.1:8080/api/v1/health` и проверьте логи `api`.
- Полный сброс volumes намеренно не включён в `demo.sh down`; удаляйте их отдельно,
  только если действительно хотите стереть локальные модели, данные и demo-БД.
