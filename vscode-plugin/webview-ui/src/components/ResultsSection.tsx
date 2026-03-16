import React from "react";
import type { MapResults, ImplementResults, MapSpecResult, BatchResult, ChangedFile } from "../types";

// ---------------------------------------------------------------------------
// Map results
// ---------------------------------------------------------------------------

interface MapResultsViewProps {
  results: MapResults;
  onOpenFile?: (path: string) => void;
  onRerunUnmapped?: () => void;
}

export function MapResultsView({ results, onOpenFile: _onOpenFile, onRerunUnmapped }: MapResultsViewProps) {
  const [filter, setFilter] = React.useState<"all" | MapSpecResult["status"]>("all");
  const [search, setSearch] = React.useState("");

  const visible = results.specs.filter((s) => {
    if (filter !== "all" && s.status !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        s.specId.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        (s.symbols ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="results-section">
      <div className="results-meta">
        ✓ Complete · {results.totalSpecs} specs · {results.subunitCount} subunits ·{" "}
        {fmtElapsed(results.elapsedSec)} · {fmtTokens(results.tokens)}
      </div>

      {/* Summary cards */}
      <div className="summary-row">
        <SummaryCard color="green" label="Mapped" value={results.mapped} />
        <SummaryCard color="yellow" label="Partial" value={results.partial} />
        <SummaryCard color="red" label="Blocked" value={results.blocked} />
        <SummaryCard color="gray" label="Unmapped" value={results.unmapped} />
      </div>

      {/* Filter + search */}
      <div className="results-toolbar">
        <select className="field-select" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
          <option value="all">All</option>
          <option value="mapped">Mapped</option>
          <option value="partial">Partial</option>
          <option value="blocked">Blocked</option>
          <option value="unmapped">Unmapped</option>
        </select>
        <input
          className="field-input"
          type="search"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Results table */}
      <div className="results-table-wrap">
        <table className="results-table">
          <thead>
            <tr>
              <th>Spec ID</th>
              <th>Title</th>
              <th>Status</th>
              <th>Confidence</th>
              <th>Code Symbol</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((s) => (
              <MapSpecRow key={s.specId} spec={s} />
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <div className="results-empty">No specs match the current filter.</div>
        )}
      </div>

      {/* Actions */}
      <div className="action-row">
        {(results.blocked > 0 || results.unmapped > 0) && (
          <button className="btn btn--secondary" onClick={onRerunUnmapped}>
            ↺ Re-run Unmapped Only
          </button>
        )}
        <button
          className="btn btn--ghost"
          onClick={() => navigator.clipboard?.writeText(results.runId)}
        >
          Copy Run ID
        </button>
      </div>
    </div>
  );
}

function MapSpecRow({ spec }: { spec: MapSpecResult }) {
  return (
    <tr className={`spec-row spec-row--${spec.status}`}>
      <td className="spec-id">{spec.specId}</td>
      <td>{spec.title || "—"}</td>
      <td>
        <StatusBadge status={spec.status} />
      </td>
      <td>{spec.confidence !== undefined ? spec.confidence.toFixed(2) : "—"}</td>
      <td className="spec-symbol">{spec.symbols ? truncate(spec.symbols, 40) : "—"}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Implement results
// ---------------------------------------------------------------------------

interface ImplementResultsViewProps {
  results: ImplementResults;
  onOpenFile: (path: string) => void;
  onRetryFailed?: () => void;
}

export function ImplementResultsView({ results, onOpenFile, onRetryFailed }: ImplementResultsViewProps) {
  return (
    <div className="results-section">
      <div className="results-meta">
        ✓ Complete · {results.implementedSpecs}/{results.totalSpecs} specs ·{" "}
        {results.batches.length} batches · {fmtElapsed(results.elapsedSec)} ·{" "}
        {fmtTokens(results.tokens)}
      </div>

      {/* Summary */}
      <div className="summary-row">
        <SummaryCard color="green" label="Implemented" value={results.implementedSpecs} />
        {results.failedSpecs > 0 && (
          <SummaryCard color="red" label="Failed" value={results.failedSpecs} />
        )}
        <SummaryCard color="blue" label="Files Changed" value={results.filesChanged.length} />
      </div>

      {/* Module breakdown */}
      {results.moduleBreakdown && Object.keys(results.moduleBreakdown).length > 0 && (
        <div className="module-grid">
          {Object.entries(results.moduleBreakdown).map(([mod, count]) => (
            <div key={mod} className="module-chip">
              <span className="module-name">{mod}</span>
              <span className="module-count">{count}</span>
            </div>
          ))}
        </div>
      )}

      {/* Batch results */}
      {results.batches.length > 0 && (
        <div className="section-card">
          <div className="section-header">
            <span className="section-title">Batch Results</span>
          </div>
          <div className="section-body">
            {results.batches.map((b) => (
              <BatchResultRow key={b.batchId} batch={b} />
            ))}
          </div>
        </div>
      )}

      {/* Files changed */}
      {results.filesChanged.length > 0 && (
        <div className="section-card">
          <div className="section-header">
            <span className="section-title">Files Changed ({results.filesChanged.length})</span>
          </div>
          <div className="section-body">
            {results.filesChanged.map((f) => (
              <FileChangedRow key={f.path} file={f} onOpen={onOpenFile} />
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="action-row">
        {results.failedSpecs > 0 && (
          <button className="btn btn--secondary" onClick={onRetryFailed}>
            ↺ Retry Failed Batches
          </button>
        )}
        <button
          className="btn btn--ghost"
          onClick={() => navigator.clipboard?.writeText(results.runId)}
        >
          Copy Run ID
        </button>
      </div>
    </div>
  );
}

function BatchResultRow({ batch }: { batch: BatchResult }) {
  const [expanded, setExpanded] = React.useState(false);
  const icon = batch.testsPassed === false ? "✗" : "✓";
  const testLabel =
    batch.testsPassed === true ? "Tests ✓" : batch.testsPassed === false ? "Tests ✗" : "";

  return (
    <div className={`batch-result-row ${batch.testsPassed === false ? "batch-result-row--failed" : ""}`}>
      <div className="batch-result-header" onClick={() => setExpanded((e) => !e)}>
        <span className="batch-result-icon">{icon}</span>
        <span className="batch-result-label">
          Batch {batch.batchId}{batch.module ? ` · ${batch.module}` : ""}
        </span>
        <span className="batch-result-specs">{batch.specIds.join(", ")}</span>
        <span className="batch-result-meta">
          {testLabel} · {batch.filesChanged} files
        </span>
        <span className="batch-chevron">{expanded ? "▲" : "▼"}</span>
      </div>
      {expanded && batch.testOutput && (
        <pre className="batch-test-output">{batch.testOutput}</pre>
      )}
    </div>
  );
}

function FileChangedRow({ file, onOpen }: { file: ChangedFile; onOpen: (p: string) => void }) {
  return (
    <div className="file-changed-row">
      <span className="file-changed-path">{file.path}</span>
      <span className="file-changed-diff">
        {file.added > 0 && <span className="diff-added">+{file.added}</span>}
        {file.removed > 0 && <span className="diff-removed"> -{file.removed}</span>}
      </span>
      <button className="btn btn--ghost btn--small" onClick={() => onOpen(file.path)}>
        View Diff
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared atoms
// ---------------------------------------------------------------------------

function SummaryCard({
  color,
  label,
  value,
}: {
  color: "green" | "yellow" | "red" | "gray" | "blue";
  label: string;
  value: number;
}) {
  return (
    <div className={`summary-card summary-card--${color}`}>
      <span className="summary-value">{value}</span>
      <span className="summary-label">{label}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: MapSpecResult["status"] }) {
  const labels: Record<MapSpecResult["status"], string> = {
    mapped: "🟢 mapped",
    partial: "🟡 partial",
    unmapped: "⚪ unmapped",
    blocked: "🔴 blocked",
  };
  return <span className={`status-badge status-badge--${status}`}>{labels[status]}</span>;
}

function fmtElapsed(secs: number): string {
  if (!secs) return "";
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function fmtTokens(n: number): string {
  if (!n) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k tokens` : `${n} tokens`;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
