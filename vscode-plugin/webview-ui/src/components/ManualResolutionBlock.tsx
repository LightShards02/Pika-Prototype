import React from "react";
import type { ManualResolutionItem, ManualResolution } from "../types";

interface Props {
  items: ManualResolutionItem[];
  onRetry: (resolutions: ManualResolution[]) => void;
}

/**
 * Displayed when the PIKA CLI halts and requires manual resolution.
 * All items must be acknowledged before Retry is enabled.
 */
export function ManualResolutionBlock({ items, onRetry }: Props) {
  const [resolutions, setResolutions] = React.useState<Record<string, ManualResolution>>(() =>
    Object.fromEntries(
      items.map((item) => [
        item.id,
        { id: item.id, note: "", suggestedValue: item.suggestions?.[0] },
      ])
    )
  );
  const [resolved, setResolved] = React.useState<Set<string>>(new Set());

  const allResolved = items.every((item) => resolved.has(item.id));

  const markResolved = (id: string) => {
    setResolved((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  const updateNote = (id: string, note: string) => {
    setResolutions((prev) => ({ ...prev, [id]: { ...prev[id], note } }));
  };

  const updateSuggested = (id: string, suggestedValue: string) => {
    setResolutions((prev) => ({ ...prev, [id]: { ...prev[id], suggestedValue } }));
  };

  return (
    <div className="manual-block">
      <div className="manual-block__header">
        <span className="manual-block__icon">⚠</span>
        <span className="manual-block__title">Manual Resolution Required</span>
        <span className="manual-block__count">
          {resolved.size}/{items.length} resolved
        </span>
      </div>
      <p className="manual-block__desc">
        The following items cannot be resolved automatically. Resolve each one and click Retry.
      </p>

      {items.map((item, idx) => {
        const isResolved = resolved.has(item.id);
        const res = resolutions[item.id] ?? { id: item.id, note: "" };
        return (
          <div key={item.id} className={`resolution-card ${isResolved ? "resolution-card--resolved" : ""}`}>
            <div className="resolution-card__header">
              <span className="resolution-card__index">[{idx + 1}/{items.length}]</span>
              <span className="resolution-card__entity">
                {item.entityType} · {item.entityId}
              </span>
              {isResolved && <span className="resolution-card__check">✓ Resolved</span>}
            </div>
            <div className="resolution-card__reason">
              <strong>Reason:</strong> {item.reason}
            </div>
            {item.details && (
              <div className="resolution-card__details">{item.details}</div>
            )}

            {item.suggestions && item.suggestions.length > 0 && (
              <div className="field-row field-row--short">
                <label className="field-label">Suggested value</label>
                <select
                  className="field-select"
                  value={res.suggestedValue ?? ""}
                  onChange={(e) => updateSuggested(item.id, e.target.value)}
                >
                  {item.suggestions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                  <option value="">— custom —</option>
                </select>
              </div>
            )}

            <div className="field-row">
              <label className="field-label">Resolution note</label>
              <input
                className="field-input"
                type="text"
                placeholder="Describe your resolution…"
                value={res.note}
                onChange={(e) => updateNote(item.id, e.target.value)}
              />
            </div>

            {!isResolved && (
              <button
                className="btn btn--primary btn--small"
                onClick={() => markResolved(item.id)}
              >
                ✓ Mark Resolved
              </button>
            )}
          </div>
        );
      })}

      <button
        className="btn btn--primary"
        disabled={!allResolved}
        onClick={() => onRetry(Object.values(resolutions))}
      >
        ▶ Retry with Resolutions
      </button>
    </div>
  );
}
