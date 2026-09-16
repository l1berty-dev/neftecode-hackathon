# Этап E разработчика 2: координатор, объяснение и trace

Срез 2026-09-15. Полный детерминированный Python-путь реализован:
проверка snapshot/policy → оценка baseline → генерация + operator action →
единый evaluator → hard feasibility/отбор → общий Decision с объяснением и trace.
Новых агентов, DTO, LLM, HTTP или обращений к PostgreSQL в этом пути нет.
Это завершение технического E второго разработчика, **не** завершение E первого
(модель причинного эффекта вмешательства). Реальные controls всё ещё закрыты.

## Фактическая реализация

- `orchestration/coordinator.py`: композиция зависимостей и один конечный цикл,
  без раундов «обсуждения» и пересчёта действия другим способом.
- `orchestration/explanation.py`: обычные чистые функции представления фактов;
  они не выбирают действия, не меняют admissibility и не вычисляют новые прогнозы.
- `optimization/candidates.py` и `optimization/ranking.py`: генерация и отбор D.
  Ranking теперь передаёт точное основание выигрыша (метрика, baseline/preferred,
  unit/basis/tolerance), применённые координаты порядка и причины их пропуска.
- Общие `Action`, `ProcessSnapshot`, `ScenarioEvaluation`, `Decision`, `TraceEntry`
  остаются из `contracts.py`. Контракт, fixture и JSON Schema не менялись.

Входы копируются/валидируются на границах. Baseline оценивается **до** генерации
остальных вариантов. Системные и операторские действия проходят тот же evaluator;
origin/label не влияют на расчёт и выбор. Мутации maps тестовым агентом не
затрагивают snapshot/операторский action вызывающего кода.

## Объяснение

`Decision.explanation` строится только из snapshot, policy, evaluations и
результатов селектора. Оно содержит:

- исход и причину: изменение по модельному преимуществу, сохранить настройки,
  недостаточно данных либо нет оценённого допустимого варианта;
- видимый replay/manual, время и версии snapshot/модели/ограничений;
- baseline и рассчитанные значения серы/интервала, forecast_at, coverage target;
- для выбранного действия и до двух альтернатив: текущие → новые абсолютные
  значения, название управления, подтверждённую единицу либо явную неизвестность,
  source, measured_at, available_at, возраст и качество текущего измерения;
- будущий выпуск и затраты с unit/basis/объяснением; severity как статический proxy,
  не вероятность аварии или ресурс катализатора;
- результаты checks выбранного варианта с code, состоянием, actual/limit/unit
  и исходным сообщением, включая информативные/неоценённые проверки;
- точное основание выбора и применённый порядок альтернатив: цели, значимость,
  нормированное вмешательство, канонический tie-break; нет обещания выигрыша
  по пропущенным или неизвестным метрикам;
- причины отказов, ограничения качества/надёжности, неизвестное и свежесть.

Unsupported/insufficient quality не получает прогнозных чисел. Неизвестный
выпуск/затраты/индекс печатаются «не оценено», не нулём. Стоимость не становится
экономией; runtime не добавляет рубли или проценты без исходных данных.
Повторяющиеся предупреждения объединяются, но одинаковые metric facts не
удаляются из блоков разных сценариев: unknown остаётся видимым у каждого.

Transition flag не объявляется гарантией безопасности. Для непустого выбора
есть явное предупреждение: модельный результат альтернативы не доказывает
промышленный эффект. Система рекомендует, но не исполняет команды.

## Trace

Trace — журнал вызовов, результатов и причин, не скрытое рассуждение или
вымышленный диалог. Порядок соответствует реальному расчёту:

1. `snapshot_validation`: snapshot ID, время, mode, completeness, версии и issues.
2. `scenario_evaluator`: baseline с snapshot/action IDs и evaluation ID в результате.
3. `candidate_generation`: фактическое число системных/итоговых actions, число
   заменённых дублей и их action IDs. Генератор вызывается один раз.
4. `scenario_evaluator`: по одному результату каждого оставшегося action.
   Содержит качество, unit/basis, проверки и их code/message/actual/limit,
   факторы с вкладом/формулой и reasons/limitations. Не объявляет внутренний
   вызов агента выполненным, если evaluator его пропустил.
5. `selection`: input IDs всех полученных evaluations, status, preferred ID либо
   null, IDs альтернатив/отказов и фактические основания отбора.

Всего N+3 entries для N реальных вызовов evaluator; максимум 28 таких вызовов.
Полный результат каждого допустимого, но не попавшего в две альтернативы,
остаётся в trace. Отказы дополнительно сохраняются в rejected_evaluations.
Чтение trace позволяет связать входной action, его расчёт и результат выбора.
Случайные evaluation/decision IDs меняются при новом расчёте; это не изменение
алгоритма. Порядок/исход при одинаковых данных и policy детерминированы.

## Передача разработчику 1

API должен использовать этот Coordinator и общий контракт, не копировать
генератор/селектор и не создавать другой путь operator evaluation.
Явные зависимости: общий `ScenarioPolicy`, активный `QualityAgent`,
`ReliabilityAgent`, `RankingPolicy`; snapshot получает provider первого.
При отсутствии артефактов ошибка явная, synthetic agent в production не загружается.

Пример композиции **из корня репозитория**, после локальных prepare/train:

```python
from datetime import UTC, datetime
from pathlib import Path

from neftecode_hackathon.data import SnapshotProvider
from neftecode_hackathon.orchestration import Coordinator
from neftecode_hackathon.quality.forecast import ForecastQualityAgent
from neftecode_hackathon.reliability import SeverityProxyAgent
from neftecode_hackathon.scenarios import ScenarioEvaluator
from neftecode_hackathon.scenarios.config import (
    load_policy,
    load_ranking_policy,
    load_severity_policy,
)

root = Path.cwd()
policy = load_policy(root / "config/controls.yaml", root / "config/constraints.yaml")
quality = ForecastQualityAgent.from_repository(root)
provider = SnapshotProvider.from_repository(root, policy=policy)
evaluator = ScenarioEvaluator(
    quality,
    SeverityProxyAgent(load_severity_policy(root / "config/severity.yaml")),
    model_version=quality.model_version,
    policy=policy,
)
coordinator = Coordinator(
    evaluator, ranking_policy=load_ranking_policy(root / "config/ranking.yaml")
)
snapshot = provider.get_snapshot(datetime(2026, 8, 6, 21, tzinfo=UTC))
decision = coordinator.decide(snapshot, horizon_minutes=60)
```

На момент завершения E разработчика 2 пример показывал только интерфейсы: локальные
data/artifacts отсутствовали. После передачи E разработчика 1 они воспроизведены, и
тот же production composition прошёл real smoke на `2026-08-06T21:00:00Z`.
При controls=false, неизвестных coverage policy и inventory промышленная рекомендация
по-прежнему не разрешается даже при supported baseline.

## Воспроизводимый пример результата и проверки

`tests/test_coordinator_explanation.py::test_synthetic_operator_example_has_exact_facts_and_selection_reason`
проверяет сокращённый сценарий: одно synthetic управление P8=150, шаг 1,
оператор предлагает 155; системные 149/150/151 дают synthetic выпуск 100,
операторский action — 105 synthetic-t/h. Это явно **тестовая** зависимость,
не физический закон и не обычный production fallback. Tolerance=1 synthetic-t/h
задан с тестовой provenance. Получается:

- status=`change_recommended`, preferred=операторский `{ht:P8: 155}`;
- текущие → новые `150 → 155 synthetic-C`;
- сера `7.8`, интервал `[6.1, 9.5] mg/kg`, coverage target `0.9` — synthetic;
- baseline/preferred выпуск `100/105`, basis=predicted;
- затраты и severity не оценены, transition_assessed=false;
- 4 вызова evaluator, 7 entries trace и две разные допустимые альтернативы.

```sh
uv run pytest tests/test_coordinator_explanation.py -q
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

9 новых E-тестов проверяют точность текста, отсутствие вымышленных эффектов,
все четыре исхода, отказ до модели при недостатке данных, repair без обещания
экономии/безопасности, единицы, ссылки trace, operator payload и JSON round-trip.
Исторический прогон E разработчика 2: 172 passed, 2 skipped. После action-readiness E
разработчика 1 было 173 passed; текущий интеграционный аудит — 174 passed, 2 skipped.
Ruff прошёл.
PostgreSQL opt-in тесты, миграции и реальный smoke в E не запускались; БД не менялась.

Следующий собственный этап второго — F: проверить/дополнить repositories,
идемпотентное сохранение и replay persistence на отдельном PostgreSQL. Затем API
первого и frontend второго. Подготовительная инфраструктура F уже существует,
но завершение E не объявляет весь сквозной API/БД/UI готовым продуктом.
