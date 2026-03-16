import React from "react";
import type { ProgressData } from "../types";

// ---------------------------------------------------------------------------
// Map progress
// ---------------------------------------------------------------------------

export interface SubunitItem {
  name: string;
  specCount: number;
  status: "pending" | "running" | "done";
  mapped?: number;
  partial?: number;
}

interface MapProgressProps {
  subunits: SubunitItem[];
  streamLines: string[];
  elapsed: number;
  tokens: number;
  onCancel: () => void;
}

export function MapProgress({ subunits, streamLines, elapsed, tokens, onCancel }: MapProgressProps) {
  const done = subunits.filter((s) => s.status === "done").length;
  const total = subunits.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const streamRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll stream
  React.useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [streamLines.length]);

  return (
    <div className="progress-section">
      <div className="progress-header">
        <span className="progress-label">
          {done}/{total} subunits&nbsp;&nbsp;·&nbsp;&nbsp;
          {fmtElapsed(elapsed)}&nbsp;&nbsp;·&nbsp;&nbsp;
          {fmtTokens(tokens)}
        </span>
        <button className="btn btn--secondary btn--small" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="progress-bar-track">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>

      <div className="subunit-list">
        {subunits.map((s) => (
          <SubunitRow key={s.name} item={s} />
        ))}
      </div>

      {streamLines.length > 0 && (
        <details open className="stream-details">
          <summary className="stream-summary">Agent stream</summary>
          <div className="stream-log" ref={streamRef}>
            {streamLines.slice(-200).map((l, i) => (
              <div key={i} className="stream-line">
                {l}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function SubunitRow({ item }: { item: SubunitItem }) {
  const icon =
    item.status === "done" ? "✓" : item.status === "running" ? "●" : "○";
  return (
    <div className={`subunit-row subunit-row--${item.status}`}>
      <span className="subunit-icon">{icon}</span>
      <span className="subunit-name">{item.name}</span>
      {item.status === "running" && <span className="subunit-hint">running…</span>}
      {item.status === "done" && (
        <span className="subunit-hint">
          {item.mapped ?? 0} mapped, {item.partial ?? 0} partial
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Implement progress
// ---------------------------------------------------------------------------

const PHASES = ["A: Preprocess", "B: Plan", "C: Briefs", "D: Execute", "E: Update"];

export interface BatchItem {
  batchId: number;
  specIds: string[];
  module?: string;
  status: "pending" | "running" | "done" | "failed";
  filesChanged?: number;
  testsPassed?: boolean;
  streamLines?: string[];
}

interface ImplementProgressProps {
  currentPhaseIndex: number;
  currentPhaseLabel: string;
  batches: BatchItem[];
  streamLines: string[];
  elapsed: number;
  tokens: number;
  onCancel: () => void;
}

export function ImplementProgress({
  currentPhaseIndex,
  currentPhaseLabel,
  batches,
  streamLines,
  elapsed,
  tokens,
  onCancel,
}: ImplementProgressProps) {
  const streamRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [streamLines.length]);

  return (
    <div className="progress-section">
      <div className="progress-header">
        <span className="progress-label">
          {fmtElapsed(elapsed)}&nbsp;&nbsp;·&nbsp;&nbsp;{fmtTokens(tokens)}
        </span>
        <button className="btn btn--secondary btn--small" onClick={onCancel}>
          Cancel
        </button>
      </div>

      {/* Phase stepper */}
      <div className="phase-stepper">
        {PHASES.map((p, i) => (
          <React.Fragment key={p}>
            <span
              className={`phase-step ${
                i < currentPhaseIndex
                  ? "phase-step--done"
                  : i === currentPhaseIndex
                  ? "phase-step--active"
                  : "phase-step--pending"
              }`}
            >
              {i < currentPhaseIndex ? "✓ " : ""}{p}
            </span>
            {i < PHASES.length - 1 && <span className="phase-arrow">→</span>}
          </React.Fragment>
        ))}
      </div>

      {/* Current phase stream */}
      {streamLines.length > 0 && (
        <details open className="stream-details">
          <summary className="stream-summary">
            Phase {PHASES[currentPhaseIndex] ?? currentPhaseLabel}
          </summary>
          <div className="stream-log" ref={streamRef}>
            {streamLines.slice(-200).map((l, i) => (
              <div key={i} className="stream-line">
                {l}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Batch list */}
      {batches.length > 0 && (
        <div className="batch-list">
          {batches.map((b) => (
            <BatchRow key={b.batchId} item={b} />
          ))}
        </div>
      )}
    </div>
  );
}

function BatchRow({ item }: { item: BatchItem }) {
  const [expanded, setExpanded] = React.useState(item.status === "running");
  const icon =
    item.status === "done"
      ? "✓"
      : item.status === "failed"
      ? "✗"
      : item.status === "running"
      ? "●"
      : "○";

  return (
    <div className={`batch-row batch-row--${item.status}`}>
      <div className="batch-row-header" onClick={() => setExpanded((e) => !e)}>
        <span className="batch-icon">{icon}</span>
        <span className="batch-label">
          Batch {item.batchId}
          {item.module && ` · ${item.module}`}
        </span>
        <span className="batch-specs">{item.specIds.join(", ")}</span>
        {item.status === "done" && (
          <span className="batch-meta">
            {item.filesChanged ?? 0} files &nbsp;
            {item.testsPassed === true ? "· Tests ✓" : item.testsPassed === false ? "· Tests ✗" : ""}
          </span>
        )}
        {item.status === "running" && <span className="batch-meta">running…</span>}
        <span className="batch-chevron">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && item.streamLines && item.streamLines.length > 0 && (
        <div className="stream-log batch-stream">
          {item.streamLines.map((l, i) => (
            <div key={i} className="stream-line">
              {l}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m ${s}s`;
}

function fmtTokens(n: number): string {
  if (!n) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k tokens` : `${n} tokens`;
}
