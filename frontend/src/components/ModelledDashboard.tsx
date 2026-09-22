import { useEffect, useMemo, useState } from "react";
import type {
  Api,
  ModelledChainRequest,
  ModelledChainResult,
  ModelledPreset,
  ModelledRunsResponse,
} from "../api/types";
import { ApiError } from "../api/types";
import { formatDate, formatNumber, statusText } from "../format";

function copyRequest(request: ModelledChainRequest): ModelledChainRequest {
  return structuredClone(request);
}

function errorText(error: unknown) {
  if (error instanceof ApiError) return `${error.message} (${error.code})`;
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

export function ModelledDashboard({ api }: { api: Api }) {
  const [presets, setPresets] = useState<ModelledPreset[]>([]);
  const [input, setInput] = useState<ModelledChainRequest | null>(null);
  const [result, setResult] = useState<ModelledChainResult | null>(null);
  const [history, setHistory] = useState<ModelledRunsResponse["items"]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([api.modelledPresets(controller.signal), api.modelledRuns(controller.signal)])
      .then(([presetResponse, historyResponse]) => {
        const first = presetResponse.items[0] ?? null;
        setPresets(presetResponse.items);
        setInput(first ? copyRequest(first.request) : null);
        setHistory(historyResponse.items);
      })
      .catch((caught) => setError(errorText(caught)))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [api]);

  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.preset_id === input?.preset_id),
    [input?.preset_id, presets],
  );

  const choosePreset = (id: string) => {
    const preset = presets.find((item) => item.preset_id === id);
    if (!preset) return;
    setInput(copyRequest(preset.request));
    setResult(null);
    setError(null);
  };

  const patchFeed = (field: keyof ModelledChainRequest["feed"], value: number | null) => {
    setInput((current) => current && { ...current, feed: { ...current.feed, [field]: value } });
  };

  const patchControl = (field: "p8" | "t11" | "f19", value: number, operator = false) => {
    if (!Number.isFinite(value)) return;
    setInput((current) => {
      if (!current) return current;
      if (operator) {
        return {
          ...current,
          operator_controls: { ...(current.operator_controls ?? current.controls), [field]: value },
        };
      }
      return { ...current, controls: { ...current.controls, [field]: value } };
    });
  };

  const run = async () => {
    if (!input) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.createModelledRun(input);
      setResult(response.result);
      setHistory((items) => [
        {
          run_id: response.result.run_id,
          created_at: response.result.created_at,
          preset_id: response.result.request.preset_id ?? null,
          status: response.result.status,
          model_version: response.result.model_version,
        },
        ...items.filter((item) => item.run_id !== response.result.run_id),
      ]);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setLoading(false);
    }
  };

  const openRun = async (id: string) => {
    setLoading(true);
    try {
      const response = await api.modelledRun(id);
      setInput(copyRequest(response.result.request));
      setResult(response.result);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setLoading(false);
    }
  };

  if (!input && loading) return <main className="shell boot-state">Загружаем модельные сценарии…</main>;
  if (!input) return <main className="shell"><div className="error-notice" role="alert">{error ?? "Нет пресетов"}</div></main>;

  return (
    <>
      <header className="topbar modelled-topbar">
        <div><p className="eyebrow">Neftecode Advisor · modelled what-if</p><h1>АВТ → гидроочистка → блендинг</h1></div>
        <div className="model-badge"><span className="live-dot" /><div><strong>Экспериментальный режим</strong><small>горизонт 180 мин · шаг совета 60 мин</small></div></div>
      </header>
      <main className="shell modelled-shell">
        {error && <div className="error-notice" role="alert"><strong>Расчёт не выполнен</strong><span>{error}</span></div>}
        <section className="panel preset-panel">
          <div><p className="eyebrow">Начните со сценария</p><h2>{selectedPreset?.name ?? "Редактируемый сценарий"}</h2><p className="muted">{selectedPreset?.description}</p></div>
          <label>Пресет<select value={input.preset_id ?? ""} onChange={(event) => choosePreset(event.target.value)}>{presets.map((preset) => <option key={preset.preset_id} value={preset.preset_id}>{preset.name}</option>)}</select></label>
          <button className="primary-button" onClick={() => void run()} disabled={loading}>{loading ? "Считаем…" : "Рассчитать цепочку"}</button>
        </section>

        <section className="model-input-grid" aria-label="Входы модельного сценария">
          <article className="panel input-card"><p className="step-number">01</p><h2>Сырьё АВТ</h2><NumberField label="Сера прямогонного ДТ, % масс." value={input.feed.straight_run_sulfur_mass_pct} onChange={(value) => patchFeed("straight_run_sulfur_mass_pct", value)} /><NumberField label="T95, °C" value={input.feed.t95_c} onChange={(value) => patchFeed("t95_c", value)} /><NumberField label="Цетановое число" value={input.feed.cetane_number} onChange={(value) => patchFeed("cetane_number", value)} /><NumberField label="Возраст анализа, мин" value={input.feed.age_minutes} onChange={(value) => patchFeed("age_minutes", value)} /><details><summary>Входы формул ВАК ({Object.keys(input.avt_inputs ?? {}).length})</summary><div className="compact-fields">{Object.entries(input.avt_inputs ?? {}).map(([key, value]) => <NumberField key={key} label={key} value={value} onChange={(next) => setInput((current) => current && ({ ...current, avt_inputs: { ...(current.avt_inputs ?? {}), [key]: next } }))} />)}</div></details></article>
          <article className="panel input-card"><p className="step-number">02</p><h2>Гидроочистка</h2><p className="muted">Исходная шкала датасета; единицы не подтверждены.</p>{(["p8", "t11", "f19"] as const).map((field) => <NumberField key={field} label={field.toUpperCase()} value={input.controls[field]} onChange={(value) => value !== null && patchControl(field, value)} />)}{input.operator_controls && <><h3>Вариант оператора</h3>{(["p8", "t11", "f19"] as const).map((field) => <NumberField key={field} label={field.toUpperCase()} value={input.operator_controls?.[field] ?? null} onChange={(value) => value !== null && patchControl(field, value, true)} />)}</>}</article>
          <article className="panel input-card"><p className="step-number">03</p><h2>Спецификация</h2><label className="field"><span>Профиль</span><select value={input.specification.profile} onChange={(event) => setInput((current) => current && ({ ...current, specification: { ...current.specification, profile: event.target.value as typeof current.specification.profile, cetane_min: event.target.value === "k5_winter" ? 47 : current.specification.cetane_min } }))}><option value="k5_summer">K5 летнее</option><option value="k5_winter">K5 зимнее</option><option value="custom">Custom</option></select></label><NumberField label="Сера ≤, мг/кг" value={input.specification.sulfur_max_mg_kg} onChange={(value) => value !== null && setInput((current) => current && ({ ...current, specification: { ...current.specification, sulfur_max_mg_kg: value } }))} /><NumberField label="T95 ≤, °C" value={input.specification.t95_max_c} onChange={(value) => value !== null && setInput((current) => current && ({ ...current, specification: { ...current.specification, t95_max_c: value } }))} /><NumberField label="Цетановое число ≥" value={input.specification.cetane_min} onChange={(value) => value !== null && setInput((current) => current && ({ ...current, specification: { ...current.specification, cetane_min: value } }))} /></article>
          <article className="panel input-card tanks-card"><p className="step-number">04</p><h2>Резервуары и 2-EHN</h2>{input.tanks.map((tank, index) => <div className="tank-row" key={tank.component_id}><strong>{tank.name}</strong>{(["sulfur_mg_kg", "t95_c", "cetane_number", "relative_cost"] as const).map((field) => <NumberField key={field} label={field.replaceAll("_", " ")} value={tank[field]} onChange={(value) => setInput((current) => { if (!current) return current; const tanks = current.tanks.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item); return { ...current, tanks }; })} />)}</div>)}<NumberField label="2-EHN, ppm" value={input.additive_ppm} onChange={(value) => value !== null && setInput((current) => current && ({ ...current, additive_ppm: value }))} /><p className="muted">Поддержка 200–3000 ppm; стоимость присадки = 100× ДТ.</p></article>
        </section>

        {result && <ModelledResult result={result} />}

        <section className="panel history-panel"><div className="section-heading"><div><p className="eyebrow">PostgreSQL · отдельный журнал</p><h2>История модельных расчётов</h2></div></div>{history.length === 0 ? <p className="empty-state">Расчётов пока нет.</p> : <div className="history-list">{history.map((item) => <button key={item.run_id} onClick={() => void openRun(item.run_id)}><span>{formatDate(item.created_at)}</span><strong>{statusText[item.status]}</strong><small>{item.preset_id ?? "custom"} · {item.run_id.slice(0, 8)}</small></button>)}</div>}</section>
      </main>
      <footer>Модельный what-if не является промышленной уставкой и не управляет оборудованием.</footer>
    </>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number | null | undefined; onChange: (value: number | null) => void }) {
  return <label className="field"><span>{label}</span><input aria-label={label} type="number" step="any" value={value ?? ""} onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} /></label>;
}

function ModelledResult({ result }: { result: ModelledChainResult }) {
  const action = result.preferred ?? result.baseline;
  const recipe = result.blend;
  const stages = [
    { title: "Причина", value: `Сера сырья ${formatNumber(result.request.feed.straight_run_sulfur_mass_pct)}% · VAK T95 ${formatNumber(result.avt.t95_c)}°C` },
    { title: "Действие", value: action ? `P8 ${formatNumber(action.controls.p8)} · T11 ${formatNumber(action.controls.t11)} · F19 ${formatNumber(action.controls.f19)}` : "Не оценивается" },
    { title: "Прогноз качества", value: action ? `S ${formatNumber(action.quality.sulfur_mg_kg)} мг/кг · T95 ${formatNumber(action.quality.t95_c)}°C · ЦЧ ${formatNumber(action.quality.cetane_number_conservative)}` : "Нет прогноза" },
    { title: "Рецепт", value: recipe?.shares.length ? recipe.shares.map((share) => `${share.component_id} ${Math.round(share.fraction * 100)}%`).join(" · ") + ` · 2-EHN ${recipe.additive_ppm} ppm` : "Рецепт не найден" },
    { title: "Ограничения", value: result.hard_checks.length ? `${result.hard_checks.filter((check) => check.passed === true).length}/${result.hard_checks.length} обязательных проверок пройдено` : "Обязательные проверки неизвестны" },
  ];
  return <section className="result-stack"><article className={`panel result-hero ${result.status}`}><p className="eyebrow">Результат modelled run</p><h2>{statusText[result.status]}</h2><ul>{result.recommendation.map((item) => <li key={item}>{item}</li>)}</ul><div className="proxy-row"><span>severity proxy <strong>{formatNumber(action?.severity_proxy)}</strong></span><span>throughput proxy <strong>{formatNumber(action?.throughput_proxy)}</strong></span><span>energy cost proxy <strong>{formatNumber(action?.energy_cost_proxy)}</strong></span></div></article><div className="chain-flow">{stages.map((stage, index) => <article className="chain-stage" key={stage.title}><span>{String(index + 1).padStart(2, "0")}</span><h3>{stage.title}</h3><p>{stage.value}</p></article>)}</div><section className="panel comparison-panel"><div className="section-heading"><div><p className="eyebrow">Одинаковая модель · одинаковые ограничения</p><h2>Системный и операторский варианты</h2></div></div><div className="model-comparison">{[result.baseline, result.preferred, ...result.alternatives].filter((item, index, values) => item && values.findIndex((candidate) => candidate?.label === item.label && candidate?.origin === item.origin) === index).map((item) => item && <article key={`${item.origin}-${item.label}`}><span className={`admissibility ${item.admissibility}`}>{item.origin}</span><h3>{item.label}</h3><strong>{formatNumber(item.quality.sulfur_mg_kg)} мг/кг S</strong><small>P8 {formatNumber(item.controls.p8)} · T11 {formatNumber(item.controls.t11)} · F19 {formatNumber(item.controls.f19)}</small></article>)}</div></section><details className="panel technical-details"><summary>Допущения, версии и технический trace</summary><div className="detail-columns"><div><h3>Допущения</h3><ul>{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></div><div><h3>Trace</h3><ol>{result.trace.map((item) => <li key={item}>{item}</li>)}</ol></div><div><h3>Версии</h3><p>{result.model_version}</p><p>{result.constraint_version}</p></div></div></details></section>;
}
