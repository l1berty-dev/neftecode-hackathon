import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Api,
  ControlDescriptor,
  Decision,
  DecisionSummary,
  HealthResponse,
  ProcessSnapshot,
  ScenarioEvaluation,
} from "./api/types";
import { ApiError, LatestRequestGate, allEvaluations, requestKey } from "./api/types";
import { ControlEditor } from "./components/ControlEditor";
import { EvaluationCard } from "./components/EvaluationCard";
import { QualityChart } from "./components/QualityChart";
import { formatAge, formatDate, formatNumber, statusText } from "./format";

interface Props {
  api: Api;
  fixtureMode?: boolean;
}

export default function App({ api, fixtureMode = false }: Props) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [snapshot, setSnapshot] = useState<ProcessSnapshot | null>(null);
  const [controls, setControls] = useState<ControlDescriptor[]>([]);
  const [controlIssues, setControlIssues] = useState<string[]>([]);
  const [episodeName, setEpisodeName] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [history, setHistory] = useState<DecisionSummary[]>([]);
  const [changes, setChanges] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [stale, setStale] = useState(false);
  const [standaloneEvaluation, setStandaloneEvaluation] = useState<ScenarioEvaluation | null>(null);
  const [standaloneLoading, setStandaloneLoading] = useState(false);
  const [standaloneError, setStandaloneError] = useState<string | null>(null);
  const [externalSnapshot, setExternalSnapshot] = useState<ProcessSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gateRef = useRef(new LatestRequestGate());
  const evaluationGateRef = useRef(new LatestRequestGate());
  const replayAbortRef = useRef<AbortController | null>(null);
  const navigationRef = useRef(0);

  const runDecision = useCallback(
    async (sourceSnapshot: ProcessSnapshot, nextChanges: Record<string, number>) => {
      const key = requestKey(sourceSnapshot.snapshot_id, nextChanges);
      const token = gateRef.current.begin(key);
      setLoading(true);
      setError(null);
      try {
        const response = await api.decide(
          {
            snapshot_id: sourceSnapshot.snapshot_id,
            horizon_minutes: 60,
            operator_action:
              Object.keys(nextChanges).length === 0
                ? null
                : { label: "Вариант оператора", changes: nextChanges },
          },
          token.signal,
        );
        if (!gateRef.current.isCurrent(token, key)) return;
        setDecision(response.decision);
        setSelectedId(response.decision.preferred?.evaluation_id ?? response.decision.baseline.evaluation_id);
        setStale(response.stale || response.current_snapshot_id !== sourceSnapshot.snapshot_id);
        setSaved(false);
      } catch (caught) {
        if ((caught as Error).name === "AbortError") return;
        if (!gateRef.current.isCurrent(token, key)) return;
        setError(apiErrorMessage(caught));
      } finally {
        if (gateRef.current.isCurrent(token, key)) setLoading(false);
      }
    },
    [api],
  );

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      setLoading(true);
      try {
        const [nextHealth, nextControls, availableEpisodes, savedHistory] = await Promise.all([
          api.health(controller.signal),
          api.controls(controller.signal),
          api.episodes(controller.signal),
          api.savedDecisions(controller.signal),
        ]);
        const defaultEpisode = availableEpisodes.episodes[0] ?? null;
        let current: Awaited<ReturnType<Api["currentSnapshot"]>>;
        try {
          current = await api.currentSnapshot(controller.signal);
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 404) throw caught;
          current = await api.startReplay(defaultEpisode?.episode_id ?? null, controller.signal);
        }
        if (controller.signal.aborted) return;
        setHealth(nextHealth);
        setControls(nextControls.controls);
        setControlIssues(nextControls.review_issues);
        setEpisodeName(defaultEpisode?.name ?? null);
        setSnapshot(current.snapshot);
        setHistory(savedHistory.items);
        await runDecision(current.snapshot, {});
      } catch (caught) {
        if ((caught as Error).name !== "AbortError") {
          setError(apiErrorMessage(caught));
          setLoading(false);
        }
      }
    })();
    return () => {
      controller.abort();
      gateRef.current.cancel();
    };
  }, [api, runDecision]);

  useEffect(() => {
    if (!running || editing || !snapshot) return;
    const timer = window.setTimeout(() => {
      const controller = new AbortController();
      replayAbortRef.current = controller;
      setLoading(true);
      void api
        .advanceReplay(snapshot.snapshot_id, controller.signal)
        .then(async (response) => {
          if (controller.signal.aborted) return;
          setSnapshot(response.snapshot);
          setChanges({});
          setStandaloneEvaluation(null);
          setStandaloneError(null);
          setStale(false);
          await runDecision(response.snapshot, {});
        })
        .catch(async (caught) => {
          if ((caught as Error).name === "AbortError") return;
          if (caught instanceof ApiError && caught.status === 409 && caught.code !== "FIXTURE_END") {
            try {
              const current = await api.currentSnapshot(controller.signal);
              setExternalSnapshot(current.snapshot);
              setStale(true);
              setRunning(false);
              setError("Replay изменился извне. Перейдите к новому снимку и пересчитайте совет.");
              return;
            } catch (refreshError) {
              setError(apiErrorMessage(refreshError));
            }
          } else {
            setError(apiErrorMessage(caught));
          }
          setRunning(false);
          setLoading(false);
        });
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [api, editing, runDecision, running, snapshot]);

  useEffect(() => {
    if (!editing || !snapshot) return;
    const timer = window.setInterval(() => {
      void api.currentSnapshot().then((response) => {
        if (response.current_snapshot_id !== snapshot.snapshot_id) {
          setExternalSnapshot(response.snapshot);
          setStale(true);
        }
      }).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [api, editing, snapshot]);

  useEffect(
    () => () => {
      replayAbortRef.current?.abort();
      evaluationGateRef.current.cancel();
    },
    [],
  );

  const evaluations = useMemo(() => (decision ? allEvaluations(decision) : []), [decision]);
  const selectedEvaluation = useMemo<ScenarioEvaluation | null>(
    () => evaluations.find((item) => item.evaluation_id === selectedId) ?? evaluations[0] ?? null,
    [evaluations, selectedId],
  );

  const updateChange = (signalId: string, value: number) => {
    if (!Number.isFinite(value)) return;
    replayAbortRef.current?.abort();
    setRunning(false);
    setEditing(true);
    setStandaloneEvaluation(null);
    setStandaloneError(null);
    setChanges((previous) => ({ ...previous, [signalId]: value }));
  };

  const resetChange = (signalId: string) => {
    setChanges((previous) => {
      const next = { ...previous };
      delete next[signalId];
      if (Object.keys(next).length === 0) setEditing(false);
      setStandaloneEvaluation(null);
      setStandaloneError(null);
      return next;
    });
  };

  const evaluateOnly = async () => {
    if (!snapshot || Object.keys(changes).length === 0 || standaloneLoading) return;
    const key = `scenario:${requestKey(snapshot.snapshot_id, changes)}`;
    const token = evaluationGateRef.current.begin(key);
    setStandaloneLoading(true);
    setStandaloneError(null);
    try {
      const response = await api.evaluate(
        { snapshot_id: snapshot.snapshot_id, horizon_minutes: 60, changes },
        token.signal,
      );
      if (!evaluationGateRef.current.isCurrent(token, key)) return;
      setStandaloneEvaluation(response.evaluation);
      if (response.stale || response.current_snapshot_id !== snapshot.snapshot_id) setStale(true);
    } catch (caught) {
      if ((caught as Error).name === "AbortError") return;
      if (evaluationGateRef.current.isCurrent(token, key)) {
        setStandaloneError(apiErrorMessage(caught));
      }
    } finally {
      if (evaluationGateRef.current.isCurrent(token, key)) setStandaloneLoading(false);
    }
  };

  const useExternalSnapshot = () => {
    if (!externalSnapshot) return;
    setSnapshot(externalSnapshot);
    setExternalSnapshot(null);
    setChanges({});
    setStandaloneEvaluation(null);
    setStandaloneError(null);
    setEditing(false);
    setStale(false);
    void runDecision(externalSnapshot, {});
  };

  const openSaved = async (summary: DecisionSummary) => {
    const generation = ++navigationRef.current;
    setLoading(true);
    setError(null);
    try {
      const [stored, original] = await Promise.all([
        api.decision(summary.decision_id),
        api.snapshot(summary.snapshot_id),
      ]);
      if (generation !== navigationRef.current) return;
      setDecision(stored.decision);
      setSnapshot(original.snapshot);
      setSelectedId(stored.decision.preferred?.evaluation_id ?? stored.decision.baseline.evaluation_id);
      setChanges({});
      setStandaloneEvaluation(null);
      setStandaloneError(null);
      setEditing(false);
      setRunning(false);
      setStale(stored.stale || stored.current_snapshot_id !== original.snapshot.snapshot_id);
      setSaved(true);
    } catch (caught) {
      if (generation === navigationRef.current) setError(apiErrorMessage(caught));
    } finally {
      if (generation === navigationRef.current) setLoading(false);
    }
  };

  const save = async () => {
    if (!decision || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.saveDecision(decision.decision_id);
      setSaved(true);
      const refreshed = await api.savedDecisions();
      setHistory(refreshed.items);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  if (!snapshot) {
    return (
      <main className="shell boot-state">
        {fixtureMode && <FixtureBanner />}
        <div className="panel"><p className="eyebrow">Гидроочистка 24-2000</p><h1>{loading ? "Загружаем состояние…" : "Нет доступного снимка"}</h1>{error && <ErrorNotice message={error} />}</div>
      </main>
    );
  }

  return (
    <>
      {fixtureMode && <FixtureBanner />}
      <header className="topbar">
        <div>
          <p className="eyebrow">Советчик оператору · только рекомендации</p>
          <h1>Гидроочистка 24-2000</h1>
        </div>
        <div className="replay-status">
          <span className="live-dot" />
          <div><strong>Replay · {running ? "идёт" : "пауза"}</strong><span>{episodeName ?? "эпизод не указан"} · {formatDate(snapshot.as_of)} МСК</span></div>
          <button className="icon-button" onClick={() => setRunning((value) => !value)} disabled={editing || loading} aria-label={running ? "Поставить replay на паузу" : "Запустить replay"}>{running ? "Ⅱ" : "▶"}</button>
        </div>
      </header>

      <main className="shell">
        {error && <ErrorNotice message={error} />}
        {stale && (
          <div className="stale-notice" role="status">
            <div><strong>Расчёт относится к прежнему снимку</strong><span>Не применяйте его к новому состоянию без пересчёта.</span></div>
            {externalSnapshot && <button onClick={useExternalSnapshot}>Перейти к новому снимку</button>}
          </div>
        )}

        <section className="hero-grid">
          <article className="panel decision-panel" aria-busy={loading}>
            <div className="section-heading">
              <div><p className="eyebrow">Решение на 60 минут</p><h2>{loading ? "Расчёт…" : decision ? statusText[decision.status] : "Решение не получено"}</h2></div>
              {decision && <span className={`status-orb ${decision.status}`} />}
            </div>
            {decision ? (
              <>
                <p className="decision-lead">{decision.preferred?.action.label ?? "Изменение не выбрано"}</p>
                <ul className="reason-list">{decision.explanation.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                <div className="decision-actions">
                  <button onClick={save} disabled={saving || saved || stale}>{saving ? "Сохраняем…" : saved ? "Сохранено" : "Сохранить решение"}</button>
                  <span>ID {decision.decision_id.slice(0, 8)}</span>
                </div>
              </>
            ) : <p className="muted">Ошибка API не считается технологическим отказом. Повторите расчёт после восстановления связи.</p>}
          </article>

          <article className="panel snapshot-panel">
            <p className="eyebrow">Состояние данных</p>
            <h2>{Math.round(snapshot.completeness * 100)}% полноты</h2>
            <div className="health-grid">
              <HealthItem label="Модель" ready={health?.model_ready} />
              <HealthItem label="Данные" ready={health?.data_ready} />
              <HealthItem label="Хранилище" ready={health?.database_ready} />
            </div>
            <dl className="source-list">
              {Object.entries(snapshot.values).map(([signal, measurement]) => (
                <div key={signal}><dt>{signal}</dt><dd>{formatNumber(measurement.value)} {measurement.unit ?? ""}<small>{measurement.source} · возраст {formatAge(measurement.age_seconds)}</small></dd></div>
              ))}
            </dl>
          </article>
        </section>

        <QualityChart snapshot={snapshot} evaluation={selectedEvaluation} />

        <section className="panel comparison-panel" aria-labelledby="comparison-title">
          <div className="section-heading"><div><p className="eyebrow">Один снимок · одинаковый горизонт</p><h2 id="comparison-title">Сравнение вариантов</h2></div></div>
          <div className="evaluation-grid">
            {evaluations.map((evaluation) => <EvaluationCard key={evaluation.evaluation_id} evaluation={evaluation} selected={evaluation.evaluation_id === selectedEvaluation?.evaluation_id} onSelect={() => setSelectedId(evaluation.evaluation_id)} />)}
          </div>
        </section>

        <ControlEditor controls={controls} snapshot={snapshot} changes={changes} disabled={loading} onChange={updateChange} onReset={resetChange} />
        {controlIssues.length > 0 && (
          <div className="control-review" role="note">
            <strong>Ограничения каталога управлений</strong>
            <ul>{controlIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          </div>
        )}
        {editing && (
          <div className="floating-compare">
            <span>{Object.keys(changes).length} измен. · снимок закреплён</span>
            <button className="secondary-button" onClick={() => void evaluateOnly()} disabled={standaloneLoading || loading || Object.keys(changes).length === 0}>{standaloneLoading ? "Проверяем…" : "Только проверить"}</button>
            <button onClick={() => void runDecision(snapshot, changes)} disabled={loading || Object.keys(changes).length === 0}>Сравнить варианты</button>
          </div>
        )}

        {(standaloneEvaluation || standaloneError) && (
          <section className="panel standalone-panel" aria-labelledby="standalone-title">
            <div className="section-heading">
              <div><p className="eyebrow">Не меняет выбранный совет</p><h2 id="standalone-title">Отдельная проверка действия</h2></div>
            </div>
            {standaloneError && <ErrorNotice message={standaloneError} />}
            {standaloneEvaluation && (
              <>
                <EvaluationCard evaluation={standaloneEvaluation} selected={false} onSelect={() => undefined} />
                <p className="muted">Чтобы включить этот вариант в общий выбор, нажмите «Сравнить варианты».</p>
              </>
            )}
          </section>
        )}

        {selectedEvaluation && <Details evaluation={selectedEvaluation} decision={decision} snapshot={snapshot} />}

        <section className="panel history-panel" aria-labelledby="history-title">
          <div className="section-heading"><div><p className="eyebrow">Аудит</p><h2 id="history-title">Сохранённые решения</h2></div></div>
          {history.length === 0 ? <p className="empty-state">Сохранённых решений пока нет.</p> : (
            <div className="history-list">{history.map((item) => <button key={item.decision_id} onClick={() => void openSaved(item)}><span>{formatDate(item.created_at)}</span><strong>{statusText[item.status]}</strong><small>Открыть исходный снимок {item.snapshot_id.slice(0, 8)}</small></button>)}</div>
          )}
        </section>
      </main>
      <footer>Прототип работает в режиме воспроизведения истории и не управляет оборудованием.</footer>
    </>
  );
}

function Details({ evaluation, decision, snapshot }: { evaluation: ScenarioEvaluation; decision: Decision | null; snapshot: ProcessSnapshot }) {
  return (
    <section className="panel details-panel" aria-labelledby="details-title">
      <div className="section-heading"><div><p className="eyebrow">Почему так</p><h2 id="details-title">Проверки и ограничения</h2></div></div>
      <div className="detail-columns">
        <div><h3>Жёсткие проверки</h3><ul className="check-list">{evaluation.checks.map((check) => <li key={check.code} className={check.passed === true ? "pass" : check.passed === false ? "fail" : "unknown"}><span>{check.passed === true ? "✓" : check.passed === false ? "×" : "?"}</span><div><strong>{check.message}</strong><small>{check.code} · факт {formatNumber(check.actual)} / предел {formatNumber(check.limit)} {check.unit ?? ""}</small></div></li>)}</ul></div>
        <div><h3>Тяжесть режима</h3><p className="muted">Это не вероятность аварии и не ресурс катализатора.</p><ul className="factor-list">{evaluation.reliability.factors.map((factor) => <li key={factor.name}><strong>{factor.name}: {formatNumber(factor.contribution)}</strong><span>{factor.explanation}</span></li>)}</ul>{!evaluation.reliability.transition_assessed && <p className="warning-copy">Переход к новой уставке не оценён.</p>}</div>
        <div><h3>Версии и след</h3><dl className="version-list"><div><dt>Данные</dt><dd>{snapshot.dataset_version}</dd></div><div><dt>Модель</dt><dd>{evaluation.model_version}</dd></div><div><dt>Ограничения</dt><dd>{evaluation.constraint_version}</dd></div></dl><ol className="trace-list">{decision?.trace.map((entry) => <li key={`${entry.role}-${entry.output_summary}`}><strong>{entry.role}</strong><span>{entry.output_summary}</span></li>)}</ol></div>
      </div>
    </section>
  );
}

function HealthItem({ label, ready }: { label: string; ready: boolean | undefined }) {
  return <div><span className={ready ? "ok-dot" : "bad-dot"} /><strong>{label}</strong><small>{ready === undefined ? "неизвестно" : ready ? "готово" : "не готово"}</small></div>;
}

function FixtureBanner() {
  return <div className="fixture-banner" role="status">DEMO FIXTURE · статические синтетические данные · расчёты действий недоступны</div>;
}

function ErrorNotice({ message }: { message: string }) {
  return <div className="error-notice" role="alert"><strong>Ошибка связи или контракта</strong><span>{message}</span></div>;
}

function apiErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) return `${caught.message} (${caught.code})`;
  return caught instanceof Error ? caught.message : "Неизвестная ошибка";
}
