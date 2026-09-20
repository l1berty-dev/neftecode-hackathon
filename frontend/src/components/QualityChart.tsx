import type { ProcessSnapshot, ScenarioEvaluation } from "../api/types";
import { formatDate, formatNumber } from "../format";

interface Props {
  snapshot: ProcessSnapshot;
  evaluation: ScenarioEvaluation | null;
}

const WIDTH = 720;
const HEIGHT = 270;
const PAD = 42;
const LIMIT = 10;

export function QualityChart({ snapshot, evaluation }: Props) {
  const quality = evaluation?.quality ?? null;
  const signalId = quality ? `pak:${quality.target}` : "pak:ht.product_sulfur";
  const history = snapshot.history
    .filter((point) => point.signal_id === signalId)
    .sort((a, b) => Date.parse(a.measured_at) - Date.parse(b.measured_at));
  const forecastSupported = quality?.applicability === "supported" && quality.prediction !== null;
  const forecastTime = forecastSupported ? Date.parse(quality.forecast_at) : null;
  const times = history.map((point) => Date.parse(point.measured_at)).filter(Number.isFinite);
  const start = times[0] ?? Date.parse(snapshot.as_of) - 60 * 60 * 1000;
  const end = Math.max(Date.parse(snapshot.as_of), forecastTime ?? 0, start + 1);
  const values = [
    LIMIT,
    ...history.map((point) => point.value),
    ...(forecastSupported
      ? [quality.prediction!, quality.lower ?? quality.prediction!, quality.upper ?? quality.prediction!]
      : []),
  ];
  const min = Math.min(...values) - 1;
  const max = Math.max(...values) + 1;
  const x = (time: number) => PAD + ((time - start) / (end - start)) * (WIDTH - PAD * 2);
  const y = (value: number) => HEIGHT - PAD - ((value - min) / (max - min)) * (HEIGHT - PAD * 2);
  const historyPath = history
    .map((point, index) => `${index === 0 ? "M" : "L"} ${x(Date.parse(point.measured_at))} ${y(point.value)}`)
    .join(" ");

  return (
    <section className="panel chart-panel" aria-labelledby="quality-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Контроль качества</p>
          <h2 id="quality-title">Сера на выходе</h2>
        </div>
        <span className="limit-chip">Лимит ≤ {LIMIT} мг/кг</span>
      </div>
      <svg className="quality-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="История серы и отдельная точка прогноза">
        <line x1={PAD} x2={WIDTH - PAD} y1={y(LIMIT)} y2={y(LIMIT)} className="limit-line" />
        <text x={WIDTH - PAD} y={y(LIMIT) - 8} textAnchor="end" className="chart-label">10 мг/кг</text>
        {historyPath && <path d={historyPath} className="history-line" data-testid="history-line" />}
        {history.map((point) => (
          <circle key={`${point.measured_at}-${point.value}`} cx={x(Date.parse(point.measured_at))} cy={y(point.value)} r="4" className="history-point" />
        ))}
        <line x1={x(Date.parse(snapshot.as_of))} x2={x(Date.parse(snapshot.as_of))} y1={PAD} y2={HEIGHT - PAD} className="now-line" />
        {forecastSupported && forecastTime !== null && (
          <g data-testid="forecast-point">
            {quality.lower !== null && quality.upper !== null && (
              <line x1={x(forecastTime)} x2={x(forecastTime)} y1={y(quality.upper)} y2={y(quality.lower)} className="interval-line" />
            )}
            <circle cx={x(forecastTime)} cy={y(quality.prediction!)} r="7" className="forecast-point" />
          </g>
        )}
        <text x={PAD} y={HEIGHT - 12} className="chart-label">{formatDate(new Date(start).toISOString())}</text>
        <text x={WIDTH - PAD} y={HEIGHT - 12} textAnchor="end" className="chart-label">{formatDate(new Date(end).toISOString())}</text>
      </svg>
      <div className="chart-legend">
        <span><i className="legend-dot measured" /> ПАК, история</span>
        <span><i className="legend-dot forecast" /> Прогноз одной точкой, без вымышленной траектории</span>
      </div>
      <p className="chart-summary">
        {forecastSupported
          ? `Через ${evaluation?.horizon_minutes} мин: ${formatNumber(quality.prediction)} ${quality.unit}; интервал ${formatNumber(quality.lower)}–${formatNumber(quality.upper)} ${quality.unit}.`
          : `Прогноз: ${quality?.reasons.join(" ") || "не оценено"}`}
      </p>
    </section>
  );
}
