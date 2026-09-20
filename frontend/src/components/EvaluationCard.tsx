import type { ScenarioEvaluation } from "../api/types";
import { formatNumber } from "../format";

interface Props {
  evaluation: ScenarioEvaluation;
  selected: boolean;
  onSelect: () => void;
}

export function EvaluationCard({ evaluation, selected, onSelect }: Props) {
  const quality = evaluation.quality;
  return (
    <button className={`evaluation-card ${selected ? "selected" : ""}`} onClick={onSelect} aria-pressed={selected}>
      <span className={`admissibility ${evaluation.admissibility}`}>{admissibilityLabel(evaluation.admissibility)}</span>
      <strong>{evaluation.action.label}</strong>
      <span className="origin">{originLabel(evaluation.action.origin)}</span>
      <dl>
        <div><dt>Сера через {evaluation.horizon_minutes} мин</dt><dd>{formatNumber(quality.prediction)} {quality.unit}</dd></div>
        <div><dt>Верхняя граница</dt><dd>{formatNumber(quality.upper)} {quality.unit}</dd></div>
        <div><dt>Тяжесть режима</dt><dd>{formatNumber(evaluation.reliability.severity_index)}</dd></div>
        <div><dt>Затраты</dt><dd>{formatNumber(evaluation.cost.value)} {evaluation.cost.unit ?? ""}</dd></div>
      </dl>
      <span className="card-reason">{evaluation.reasons[0] ?? quality.reasons[0] ?? "Причина не передана"}</span>
    </button>
  );
}

function admissibilityLabel(value: ScenarioEvaluation["admissibility"]) {
  return value === "admissible" ? "Допустим" : value === "rejected" ? "Отклонён" : "Не оценён";
}

function originLabel(value: ScenarioEvaluation["action"]["origin"]) {
  return value === "baseline" ? "Текущий режим" : value === "operator" ? "Вариант оператора" : "Вариант системы";
}
