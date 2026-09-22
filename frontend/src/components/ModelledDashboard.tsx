import { useEffect, useMemo, useState } from "react";
import type {
  Api,
  ModelledChainRequest,
  ModelledChainResult,
  ModelledPreset,
} from "../api/types";

type Props = { api: Api };

const statusText: Record<string, string> = {
  change_recommended: "Рекомендуется модельное изменение",
  no_change: "Сохранить настройки",
  insufficient_data: "Недостаточно данных",
  no_feasible_option: "Нет допустимого варианта",
};

const number = (value: string) => value === "" ? null : Number(value);
const display = (value: number | null | undefined, digits = 2) => value == null ? "не оценено" : value.toFixed(digits);

export function ModelledDashboard({ api }: Props) {
  const [presets, setPresets] = useState<ModelledPreset[]>([]);
  const [selected, setSelected] = useState("");
  const [request, setRequest] = useState<ModelledChainRequest | null>(null);
  const [result, setResult] = useState<ModelledChainResult | null>(null);
  const [history, setHistory] = useState<{ run_id: string; status: string; preset_id: string | null }[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [edited, setEdited] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.modelledPresets(controller.signal), api.modelledRuns(controller.signal)])
      .then(([presetResponse, runResponse]) => {
        setPresets(presetResponse.items);
        setHistory(runResponse.items);
        if (presetResponse.items[0]) {
          setSelected(presetResponse.items[0].preset_id);
          setRequest(structuredClone(presetResponse.items[0].request));
          setEdited(false);
        }
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setBusy(false));
    return () => controller.abort();
  }, [api]);

  const preset = useMemo(() => presets.find((item) => item.preset_id === selected), [presets, selected]);
  const visibleHistory = useMemo(() => {
    const seen = new Set<string>();
    return history.filter((item) => {
      const key = item.preset_id ?? "custom";
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 5);
  }, [history]);
  const choosePreset = (id: string) => {
    const next = presets.find((item) => item.preset_id === id);
    setSelected(id);
    setRequest(next ? structuredClone(next.request) : null);
    setResult(null);
    setEdited(false);
    setError(null);
  };
  const patch = (fn: (draft: ModelledChainRequest) => void) => {
    if (!request) return;
    const draft = structuredClone(request);
    fn(draft);
    setRequest(draft);
    setResult(null);
    setEdited(true);
    setError(null);
  };
  const run = async () => {
    if (!request) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.createModelledRun(request);
      setResult(response.result);
      setEdited(false);
      const updated = await api.modelledRuns();
      setHistory(updated.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось выполнить расчёт");
    } finally {
      setBusy(false);
    }
  };

  if (busy && !request) return <main className="boot-state"><p>Загрузка модельного контура…</p></main>;

  return <>
    <header className="topbar modelled-topbar"><h1>Operator Assistant</h1></header>
    <main className="shell">
      {error && <div className="error-notice" role="alert">{error}</div>}
      <section className="panel preset-panel">
        <div><p className="eyebrow">Начальный сценарий</p><h2>{preset?.name ?? "Сценарий"}</h2><p className="muted">{preset?.description}</p></div>
        <label>Пресет<select aria-label="Пресет" value={selected} onChange={(event) => choosePreset(event.target.value)}>{presets.map((item) => <option key={item.preset_id} value={item.preset_id}>{item.name}</option>)}</select></label>
        <button className="primary-button" disabled={busy || !request} onClick={run}>{busy ? "Расчёт…" : "Рассчитать цепочку"}</button>
      </section>

      {request && <section className="model-input-grid">
        <article className="panel input-card"><p className="step-number">01</p><h2>Сырьё</h2>
          <Field label="Сера прямогонного ДТ, % масс." value={request.feed.straight_run_sulfur_mass_pct} onChange={(v) => patch((d) => { d.feed.straight_run_sulfur_mass_pct = v; })}/>
          <Field label="T95, °C" value={request.feed.t95_c} onChange={(v) => patch((d) => { d.feed.t95_c = v; })}/>
          <Field label="Цетановое число" value={request.feed.cetane_number} onChange={(v) => patch((d) => { d.feed.cetane_number = v; })}/>
          <Field label="Возраст данных, мин" value={request.feed.age_minutes} onChange={(v) => patch((d) => { d.feed.age_minutes = v; })}/>
        </article>
        <article className="panel input-card"><p className="step-number">02</p><h2>Режим 24-2000</h2>
          <Field label="P8, сырая шкала" value={request.controls.p8} onChange={(v) => patch((d) => { if (v != null) d.controls.p8 = v; })}/>
          <Field label="T11, сырая шкала" value={request.controls.t11} onChange={(v) => patch((d) => { if (v != null) d.controls.t11 = v; })}/>
          <Field label="F19, сырая шкала" value={request.controls.f19} onChange={(v) => patch((d) => { if (v != null) d.controls.f19 = v; })}/>
        </article>
        <article className="panel input-card"><p className="step-number">03</p><h2>Спецификация</h2>
          <Field label="Сера, не более мг/кг" value={request.specification.sulfur_max_mg_kg} onChange={(v) => patch((d) => { if (v != null) d.specification.sulfur_max_mg_kg = v; })}/>
          <Field label="T95, не более °C" value={request.specification.t95_max_c} onChange={(v) => patch((d) => { if (v != null) d.specification.t95_max_c = v; })}/>
          <Field label="Цетановое число, не менее" value={request.specification.cetane_min} onChange={(v) => patch((d) => { if (v != null) d.specification.cetane_min = v; })}/>
          <Field label="Присадка 2-EHN, ppm" value={request.additive_ppm} onChange={(v) => patch((d) => { if (v != null) d.additive_ppm = v; })}/>
        </article>
        <article className="panel input-card tanks-card"><p className="step-number">04</p><h2>Компоненты смеси</h2>
          {request.tanks.map((tank, index) => <div className="tank-row" key={tank.component_id}><strong>{tank.name}</strong>
            <Field label="Сера, мг/кг" value={tank.sulfur_mg_kg} onChange={(v) => patch((d) => { d.tanks[index].sulfur_mg_kg = v; })}/>
            <Field label="T95, °C" value={tank.t95_c} onChange={(v) => patch((d) => { d.tanks[index].t95_c = v; })}/>
            <Field label="Цетановое" value={tank.cetane_number} onChange={(v) => patch((d) => { d.tanks[index].cetane_number = v; })}/>
            <Field label="Отн. стоимость" value={tank.relative_cost} onChange={(v) => patch((d) => { if (v != null) d.tanks[index].relative_cost = v; })}/>
          </div>)}
        </article>
      </section>}

      {request && edited && <section className="modelled-recalculate" role="status">
        <div><strong>Параметры изменены</strong><span>Предыдущий результат скрыт. Запустите цепочку, чтобы оценить именно текущие значения.</span></div>
        <button className="primary-button" disabled={busy} onClick={run}>{busy ? "Расчёт…" : "Рассчитать изменённую цепочку"}</button>
      </section>}

      {result && <section className="result-stack" aria-live="polite">
        <article className={`panel result-hero ${result.status}`}><p className="eyebrow">Результат модельного расчёта</p><h2>{statusText[result.status]}</h2><ul>{result.recommendation.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}</ul>
          {result.preferred && <div className="proxy-row"><span>Вариант: {result.preferred.label}</span><span>Сера: {display(result.preferred.quality.sulfur_mg_kg)} мг/кг</span><span>Энергия: {display(result.preferred.energy_cost_proxy)}</span></div>}
        </article>
        <div className="chain-flow"><Stage number="01" title="АВТ" text={`CFPP: ${display(result.avt.cfpp_c)} °C`}/><Stage number="02" title="Гидроочистка" text={result.preferred ? `${result.preferred.label}, сера ${display(result.preferred.quality.sulfur_mg_kg)} мг/кг` : "не оценено"}/><Stage number="03" title="Рецепт" text={result.blend ? result.blend.shares.filter((s) => s.fraction > 0).map((s) => `${s.component_id} ${Math.round(s.fraction*100)}%`).join(" · ") : "не найден"}/><Stage number="04" title="Присадка" text={`${result.request.additive_ppm} ppm`}/><Stage number="05" title="Продукт" text={result.blend ? `S ${display(result.blend.quality.sulfur_mg_kg)} · T95 ${display(result.blend.quality.t95_c)} · CN ${display(result.blend.quality.cetane_number_conservative)}` : "не оценено"}/></div>
        <details className="panel technical-details"><summary>Допущения, проверки и trace</summary><h3>Ограничения модели</h3><ul>{result.assumptions.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}</ul><h3>Обязательные проверки</h3><ul>{result.hard_checks.map((item) => <li key={item.code}>{item.passed ? "✓" : item.passed === false ? "✕" : "?"} {item.message} ({item.code})</li>)}</ul><h3>Trace</h3><ol>{result.trace.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}</ol></details>
      </section>}

      <section className="panel history-panel"><div className="section-heading"><div><h2>История модельных запусков</h2></div></div>{visibleHistory.length ? <div className="history-list">{visibleHistory.map((item) => <button key={item.run_id} onClick={() => api.modelledRun(item.run_id).then((response) => {
        setResult(response.result);
        setRequest(structuredClone(response.result.request));
        if (response.result.request.preset_id) setSelected(response.result.request.preset_id);
        setEdited(false);
        setError(null);
      }).catch((reason: Error) => setError(reason.message))}><strong>{statusText[item.status]}</strong><span>{item.preset_id ?? "без пресета"}</span><small>{item.run_id.slice(0, 8)}</small></button>)}</div> : <p className="empty-state">Запусков пока нет.</p>}</section>
    </main>
    <footer>Решение требует взгляда специалиста перед изменениями характеристик</footer>
  </>;
}

function Field({ label, value, onChange }: { label: string; value: number | null | undefined; onChange: (value: number | null) => void }) {
  return <label className="field">{label}<input aria-label={label} type="number" step="any" value={value ?? ""} onChange={(event) => onChange(number(event.target.value))}/></label>;
}

function Stage({ number, title, text }: { number: string; title: string; text: string }) {
  return <article className="chain-stage"><span>{number}</span><h3>{title}</h3><p>{text}</p></article>;
}
