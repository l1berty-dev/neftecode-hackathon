# Frontend v1 — экран советчика оператора

Дата среза: 2026-09-20. Этап G разработчика 2.

## Что реализовано

`frontend/` содержит React + TypeScript + Vite-приложение с одним основным
экраном гидроочистки 24-2000. Оно показывает replay-состояние, решение,
фактическую историю серы, отдельную прогнозную точку с интервалом, сравнение
сценариев, каталог управлений, проверки, факторы тяжести, версии/trace и историю
сохранённых решений.

Интерфейс не рассчитывает производственные показатели и не ранжирует варианты.
Все численные результаты Decision и ScenarioEvaluation поступают от API. `null`
отображается как «не оценено», ошибка API не превращается в технологический
`no_feasible_option`, а показатель тяжести не называется вероятностью аварии.
Между последним измерением и прогнозом не рисуется вымышленная траектория.

Редактирование абсолютной уставки приостанавливает локальный replay и закрепляет
исходный snapshot. Поздние ответы отбрасываются одновременно по AbortController
и монотонному поколению с ключом `snapshot_id + action + horizon`. При внешней
смене снимка результат помечается устаревшим и требует явного пересчёта.
Сохранение отправляет только server-side `decision_id`; история открывает решение
вместе с его исходным snapshot.

## Контракты и текущая граница интеграции

Доменные TypeScript-типы генерируются из
`examples/contract_v1.schema.json` командой `npm run generate:contracts`.
Файл `src/api/contracts.generated.ts` нельзя редактировать вручную. Все HTTP-вызовы
собраны в `src/api/http.ts`.

FastAPI routes и OpenAPI теперь находятся в репозитории. Транспортные envelope-типы
(`HealthResponse`, `ControlsResponse`, `SnapshotResponse`, `DecisionResponse`) остаются
изолированы в `src/api/types.ts` и сверены с `examples/openapi.v1.json`: nullable episode,
operator label/changes, controls, ошибки, save/history согласованы. Полный реальный E2E
с backend/PostgreSQL пока не заявляется выполненным.

По умолчанию приложение обращается к `/api/v1`; Vite проксирует `/api` на
`http://127.0.0.1:8000`. Статический synthetic fixture включается только через
`VITE_USE_FIXTURE=true`, всегда показывает заметный banner и намеренно не
имитирует пересчёт пользовательских действий. Fixture-режим выключен по умолчанию.

## Запуск и проверка

Требуется Node.js >=20.19.0 (либо >=22.12.0): это нижняя граница
зафиксированных Vite/jsdom-зависимостей.

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Для изолированного просмотра fixture явно измените только локальный `.env.local`:

```dotenv
VITE_USE_FIXTURE=true
```

Проверки:

```bash
npm run typecheck
npm test
npm run build
```

На срезе 2026-09-20 прошли TypeScript typecheck, 9 тестов в 4 файлах и production
build Vite. Проверены drift generated contracts, реальная UI-гонка позднего ответа,
стабильный request key и открытие истории с исходным snapshot,
отображение unknown, отсутствие вымышленной прогнозной линии, неподдерживаемый
прогноз, маркировка fixture, save по decision_id и отдельное представление ошибки API.

После объединения с FastAPI contract drift, typecheck и production build повторно
прошли. Локальный повтор Vitest на Node 20.18.1 не стартовал из-за engine requirement;
это ограничение среды, для полного повторного прогона нужен Node >=20.19.0.

`npm install` сообщил о двух moderate advisory в дереве dev-зависимостей. Автоматический
`npm audit fix --force` не выполнялся, чтобы не вносить непроверенные breaking changes;
`npm audit --omit=dev` подтвердил 0 production vulnerabilities. Перед выпуском надо
разобрать dev advisory и обновить lock-файл контролируемо.

## Следующая интеграция

1. При добавлении OpenAPI-codegen заменить согласованные envelope-типы генерируемыми.
2. Сверить реальные ответы всех достижимых DecisionStatus и ошибки 404/409/422/503.
3. Прогнать совместный путь PostgreSQL migration → replay snapshot → Decision →
   operator action → save → history и браузерную проверку узкого экрана/клавиатуры.
4. Не открывать controls, пока backend возвращает `available=false`; fixture не
   является основанием активировать реальные воздействия.
