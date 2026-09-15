# Этап B: каталог и жёсткие проверки

Реализация: `src/neftecode_hackathon/scenarios/config.py`, `checks.py`,
`evaluator.py`. Публичные результаты — прежние модели из `contracts.py`;
внутренние модели описывают только конфигурацию, не альтернативные HTTP DTO.

## Подключение

```python
from pathlib import Path
from neftecode_hackathon.scenarios.config import load_policy
from neftecode_hackathon.scenarios import ScenarioEvaluator

policy = load_policy(Path("config/controls.yaml"), Path("config/constraints.yaml"))
evaluator = ScenarioEvaluator(
    quality_agent=quality_agent,
    reliability_agent=reliability_agent,
    model_version=model_version,
    policy=policy,
)
evaluation = evaluator.evaluate(snapshot, action, horizon_minutes=60)
```

Без явного policy evaluator загружает эти два файла относительно рабочего каталога.
Для запуска из другого каталога передать абсолютные пути. Никакой БД/HTTP не нужно;
не добавлялся второй агент качества или источник тренировочных диапазонов.

Оба YAML обязаны иметь одинаковую `constraint_version`; версия приходит в результат
из policy, а не задаётся независимо. Файлы не перечитываются посреди сравнения:
новая политика требует нового evaluator. Не изменять версию без обновления политики.
Неизвестные поля, дубли YAML-ключей/ID/codes, небезопасные YAML-теги, NaN/Inf,
обратные диапазоны и неподтверждённый `available=true` вызывают явную ошибку.

## Каталог

P8/T11/F19 заменили старого кандидата F26. Смысл и управляемость имеют
`verification_status=confirmed` с evidence организаторов и ячеек справочника.
Численные единицы/шкалы, модельные диапазоны, шаги и action support отсутствуют:
в рабочем каталоге все три `available=false` с конкретной причиной.

Для `available=true` нужны:

- подтверждённая управляемость/evidence, canonical_unit и `unit_verified=true`;
- `action_support_verified=true` и `support_model_version` активной модели;
- `model_min < model_max`, положительный step, provenance диапазона/шага;
- подтверждённый manifest обязательных входов активной модели.

Train-provenance содержит kind=train, source, train_end, available_at,
dataset_version. В replay конец train и доступность политики не позже snapshot.as_of,
а версия данных должна совпадать. Expert-provenance также содержит source и aware
available_at. Приведённые поля фиксируют ответственность за обучение только на train;
проверки не могут сами доказать, что внешний автор честно сформировал диапазоны.
Диапазоны всегда помечены experimental и не являются промышленными пределами.

Шаг абсолютного значения проверяется на сетке `model_min + n*step`, с числовым
допуском 1e-9 шага. Текущее измерение baseline не обязано лежать на сетке уставок,
но обязано попадать в диапазон модели. Значения передаются абсолютно, не как дельты.
Начальная свежесть управления 1200 секунд — прежнее экспериментальное правило
online 20 минут из model.yaml, не подтверждение организаторов.

## До вызова модели

1. Неизвестное/недоступное управление, выход из диапазона, неправильный шаг или
   запрещённое сочетание → rejected, никакого вызова QualityAgent/ReliabilityAgent.
2. У всех доступных управлений проверить текущие значения/единицы/свежесть и
   provenance, в том числе в baseline. У mandatory model inputs — те же data checks.
3. Отсутствующие, suspect, устаревшие значения, неизвестные/несовпадающие единицы
   или несогласованный age_seconds → passed=null, обязательная оценка блокируется.
   Возраст вычисляется из времён, допустимое отличие age_seconds — 1 секунда.
   measured_at/available_at из будущего отклоняются контрактом до агентов.
4. `signal_limits` описывают подтверждённые minimum/maximum, signal_id, unit,
   max_age_seconds, evidence, category и required. Проверяются текущее значение
   либо новая абсолютная уставка. Их codes начинаются с policy. и уникальны.
5. `forbidden_combinations` содержат code, минимум два разных signal IDs и evidence;
   блокируют их совместное присутствие в changes. Это явная политика совместного
   задания параметров, не доказательство совместной поддержки модели.
6. Ramp limits допускаются только с ramp_evidence; реальный каталог их не задаёт
   по ответу организаторов. При наличии проверять |new-current|/transition_minutes.
   Длительность перехода задаётся отдельно, её нельзя заменить горизонтом прогноза.

Если обязательная предварительная проверка неизвестна, модель не вызывается,
forecast numbers остаются null. Проверенные нарушения имеют приоритет над неизвестностью.
Недостающие mandatory данные возвращают quality.applicability=insufficient_data.

## После вызова QualityAgent

Повторно валидируется контракт качества; неизвестные/некорректные интервалы и
числа не проходят. Несовпадение версии модели — явная ошибка. Прогноз для другой
цели/единицы/времени отклоняется и скрывается. Требуются:

- supported для данного состояния и совместного действия;
- интервал, не содержащий отрицательной серы;
- interval_coverage_target не ниже утверждённого minimum_interval_coverage;
- верхняя оценка серы <= sulfur_upper_limit, который нельзя настроить выше 10 мг/кг.

interval_coverage_target — заявленное целевое покрытие, не измеренное качество
counterfactual-интервала. Пригодность метода/ограничения обязан передать разработчик 1
с manifest/report; проверка поля не доказывает причинность и промышленную гарантию.
Минимальное покрытие пока null, поэтому реальная политика не выдаёт допустимость.

`hard_check_inventory_verified` с evidence подтверждает состав реальных обязательных
проверок. До совместного утверждения null-check блокирует admissible; proxy severity
не заменяет hard checks. Пустой список допустим только при явном утверждении inventory.
`transition_required=true` для нового действия остаётся unknown до предоставления
результата проверки перехода: одного `transition_assessed=true` недостаточно.
Ramp check проверяет только заданную скорость, не всю динамику перехода.

## Required и informative

- У обязательной проверки `passed=false` → rejected; `passed=null` → not_assessable.
- admissible только если все required results равны true.
- `signal_limits.required=false` и необязательный переход не участвуют в фильтрации.
  В публичном CheckResult обязательность пока не отдельное поле: информативные
  сообщения имеют префикс «Справочно (не hard check)». Сам контракт не менялся.
- Стоимость и будущий выпуск остаются null/unavailable; показатель тяжести может
  быть неизвестен. Отсутствие optional метрики не превращается в обязательный отказ.

Результат хранит все проверки и причины/limitations. Нет ранжирования в этапе B.
Подготовительный Coordinator явно отказывается ранжировать admissible evaluations,
пока не реализованы C–E, вместо неверного no_feasible_option при наличии допустимого
варианта. До этого пользоваться отдельным ScenarioEvaluator.evaluate.

## Проверка и оставшаяся передача

```sh
uv run pytest tests/test_scenario_checks.py tests/test_developer_2_preparation.py
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Численные единицы/диапазоны/лимиты и агенты в тестах явно synthetic. Реальные CSV
не используются для подбора границ. Реальная модель, manifest, train-only диапазоны,
шкалы управлений и политика обязательных ограничений ещё нужны от совместной передачи.
Задержка ЛИМС 240 минут остаётся задачей первого разработчика; его код/конфигурация
и общие контракты в этапе B не изменялись.
