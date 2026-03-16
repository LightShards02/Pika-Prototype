import React from "react";
import type {
  SidebarIncomingMessage,
  SidebarOutgoingMessage,
  SpecStats,
  RunHistoryEntry,
} from "../types";

interface Props {
  postMessage: (msg: SidebarOutgoingMessage) => void;
}

export function SidebarPanel({ postMessage }: Props) {
  const [stats, setStats] = React.useState<SpecStats | null>(null);
  const [history, setHistory] = React.useState<RunHistoryEntry[]>([]);
  const [activeRun, setActiveRun] = React.useState<"map" | "implement" | null>(null);

  React.useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data as SidebarIncomingMessage;
      if (msg.type === "specStats") setStats(msg.data);
      if (msg.type === "runHistory") setHistory(msg.entries);
      if (msg.type === "activeRun") setActiveRun(msg.command);
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const open = (command: "map" | "implement", dryRun?: boolean) =>
    postMessage({ type: "openPanel", command, dryRun });

  return (
    <div className="sidebar">
      {/* Design Spec section */}
      <div className="sidebar-section">
        <div className="sidebar-section-header">
          <span className="sidebar-section-title">DESIGN SPEC</span>
          <button
            className="sidebar-icon-btn"
            title="Refresh"
            onClick={() => postMessage({ type: "refresh" })}
          >
            ⟳
          </button>
        </div>

        {stats ? (
          <div className="spec-stats">
            {stats.total === 0 ? (
              <div className="spec-stats__empty">No design spec found</div>
            ) : (
              <>
                <StatRow icon="🟢" label="mapped" count={stats.mapped} />
                <StatRow icon="🟡" label="partial" count={stats.partial} />
                <StatRow icon="🔴" label="blocked" count={stats.blocked} />
                <StatRow icon="⚪" label="unmapped" count={stats.unmapped} />
                {stats.implemented > 0 && (
                  <StatRow icon="✓" label="implemented" count={stats.implemented} />
                )}
              </>
            )}
          </div>
        ) : (
          <div className="sidebar-loading">Loading…</div>
        )}
      </div>

      {/* Commands section */}
      <div className="sidebar-section">
        <div className="sidebar-section-header">
          <span className="sidebar-section-title">COMMANDS</span>
        </div>
        <div className="cmd-grid">
          <button
            className="btn btn--primary btn--full"
            disabled={activeRun !== null}
            onClick={() => open("map")}
          >
            {activeRun === "map" ? "⏳ Map running…" : "▶ Run Map"}
          </button>
          <button
            className="btn btn--secondary btn--full"
            disabled={activeRun !== null}
            onClick={() => open("map", true)}
          >
            ⊡ Dry-Run Map
          </button>
          <button
            className="btn btn--primary btn--full"
            disabled={activeRun !== null}
            onClick={() => open("implement")}
          >
            {activeRun === "implement" ? "⏳ Impl running…" : "▶ Run Implement"}
          </button>
          <button
            className="btn btn--secondary btn--full"
            disabled={activeRun !== null}
            onClick={() => open("implement", true)}
          >
            ⊡ Dry-Run Impl
          </button>
        </div>
      </div>

      {/* Run history */}
      {history.length > 0 && (
        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <span className="sidebar-section-title">RUN HISTORY</span>
          </div>
          <div className="history-list">
            {history.map((entry) => (
              <HistoryRow key={entry.runId} entry={entry} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatRow({
  icon,
  label,
  count,
}: {
  icon: string;
  label: string;
  count: number;
}) {
  return (
    <div className="stat-row">
      <span className="stat-icon">{icon}</span>
      <span className="stat-label">{label}</span>
      <span className="stat-count">({count})</span>
    </div>
  );
}

function HistoryRow({ entry }: { entry: RunHistoryEntry }) {
  const icon = entry.status === "success" ? "🟢" : entry.status === "failed" ? "🔴" : "⚪";
  const label = entry.status === "failed" ? "failed" : formatAgo(entry.timestamp);
  return (
    <div className="history-row">
      <span className="history-icon">{icon}</span>
      <span className="history-cmd">{entry.command}</span>
      <span className="history-ts">{label}</span>
    </div>
  );
}

function formatAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.round(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}
