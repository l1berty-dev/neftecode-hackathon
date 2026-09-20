import type { ControlDescriptor, ProcessSnapshot } from "../api/types";
import { formatNumber } from "../format";

interface Props {
  controls: ControlDescriptor[];
  snapshot: ProcessSnapshot;
  changes: Record<string, number>;
  disabled: boolean;
  onChange: (signalId: string, value: number) => void;
  onReset: (signalId: string) => void;
}

export function ControlEditor({ controls, snapshot, changes, disabled, onChange, onReset }: Props) {
  return (
    <section className="panel" aria-labelledby="controls-title">
      <div className="section-heading">
        <div><p className="eyebrow">Вариант оператора</p><h2 id="controls-title">Проверить своё действие</h2></div>
      </div>
      <p className="muted">Значения задаются как новые абсолютные уставки. Редактирование ставит replay на паузу.</p>
      <div className="control-list">
        {controls.length === 0 && <div className="empty-state">Каталог управлений не получен.</div>}
        {controls.map((control) => {
          const current = snapshot.values[control.signal_id]?.value ?? null;
          const value = changes[control.signal_id] ?? current ?? control.min ?? 0;
          const canEdit = control.available && current !== null && control.min !== null && control.max !== null && control.step !== null;
          return (
            <div className={`control-row ${canEdit ? "" : "disabled"}`} key={control.signal_id}>
              <div className="control-copy">
                <strong>{control.label}</strong>
                <span>{control.signal_id} · сейчас {formatNumber(current)} {control.unit ?? ""}</span>
                {!canEdit && <em>{control.reason ?? "Диапазон управления не подтверждён"}</em>}
              </div>
              <label>
                <span className="sr-only">Новое значение: {control.label}</span>
                <input
                  type="number"
                  value={value}
                  min={control.min ?? undefined}
                  max={control.max ?? undefined}
                  step={control.step ?? undefined}
                  disabled={disabled || !canEdit}
                  onChange={(event) => onChange(control.signal_id, event.currentTarget.valueAsNumber)}
                />
                <span>{control.unit}</span>
              </label>
              <button className="text-button" disabled={disabled || !(control.signal_id in changes)} onClick={() => onReset(control.signal_id)}>Сбросить</button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
