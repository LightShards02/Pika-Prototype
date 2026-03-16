import React from "react";
import {
  FileField,
  CheckboxField,
  NumberField,
  TextAreaField,
  Section,
} from "../components/InputSection";
import { MapProgress } from "../components/ProgressSection";
import { ManualResolutionBlock } from "../components/ManualResolutionBlock";
import { MapResultsView } from "../components/ResultsSection";
import type {
  PikaConfigSnapshot,
  PanelIncomingMessage,
  PanelOutgoingMessage,
  MapResults,
  ManualResolutionItem,
  ManualResolution,
  ProgressData,
  SubunitItem,
} from "../types";

// Re-export SubunitItem so ProgressSection can use it from types
import type { SubunitItem as _SI } from "../components/ProgressSection";

type PanelState = "idle" | "running" | "blocked" | "complete" | "failed";

interface Props {
  postMessage: (msg: PanelOutgoingMessage) => void;
}

export function MapPanel({ postMessage }: Props) {
  // Form state
  const [designSpec, setDesignSpec] = React.useState("");
  const [codebaseDir, setCodebaseDir] = React.useState(".");
  const [projectContext, setProjectContext] = React.useState("");
  const [skipMapped, setSkipMapped] = React.useState(true);
  const [maxPerSubunit, setMaxPerSubunit] = React.useState(15);
  const [minConfidence, setMinConfidence] = React.useState(0.7);
  const [extraInstructions, setExtraInstructions] = React.useState("");
  const [worksetCount, setWorksetCount] = React.useState<number | null>(null);

  // Run state
  const [panelState, setPanelState] = React.useState<PanelState>("idle");
  const [errorMsg, setErrorMsg] = React.useState("");
  const [elapsed, setElapsed] = React.useState(0);
  const [tokens, setTokens] = React.useState(0);
  const [streamLines, setStreamLines] = React.useState<string[]>([]);
  const [subunits, setSubunits] = React.useState<_SI[]>([]);
  const [manualItems, setManualItems] = React.useState<ManualResolutionItem[]>([]);
  const [results, setResults] = React.useState<MapResults | null>(null);

  // Listen for messages from extension host
  React.useEffect(() => {
    const handler = (event: MessageEvent) => {
      const msg = event.data as PanelIncomingMessage | { type: "browse"; field: string; value: string };
      handleMessage(msg);
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  });

  const handleMessage = (
    msg: PanelIncomingMessage | { type: "browse"; field: string; value: string }
  ) => {
    if (msg.type === "init") {
      applyConfig(msg.config);
      return;
    }
    if (msg.type === "browse") {
      if (msg.field === "designSpec") setDesignSpec(msg.value);
      if (msg.field === "codebaseDir") setCodebaseDir(msg.value);
      if (msg.field === "projectContext") setProjectContext(msg.value);
      return;
    }
    if (msg.type === "stream") {
      setElapsed(msg.elapsed);
      if (msg.tokens) setTokens(msg.tokens);
      // split chunk into lines, append to stream buffer
      const newLines = msg.text.split(/\r?\n/);
      setStreamLines((prev) => [...prev, ...newLines].slice(-500));
      return;
    }
    if (msg.type === "progress") {
      handleProgress(msg.data);
      return;
    }
    if (msg.type === "manualResolution") {
      setManualItems(msg.items);
      setPanelState("blocked");
      return;
    }
    if (msg.type === "complete" && "mapped" in msg.results) {
      setResults(msg.results as MapResults);
      setPanelState("complete");
      return;
    }
    if (msg.type === "failed") {
      setErrorMsg(msg.message);
      setPanelState("failed");
      return;
    }
  };

  const applyConfig = (cfg: PikaConfigSnapshot) => {
    if (cfg.designSpecPath) setDesignSpec(cfg.designSpecPath);
    if (cfg.codebaseDir) setCodebaseDir(cfg.codebaseDir);
    if (cfg.skipMapped !== undefined) setSkipMapped(cfg.skipMapped);
    if (cfg.maxSpecsPerSubunit) setMaxPerSubunit(cfg.maxSpecsPerSubunit);
    if (cfg.minConfidenceThreshold) setMinConfidence(cfg.minConfidenceThreshold);
  };

  const handleProgress = (data: ProgressData) => {
    if (data.type === "subunitStart") {
      setSubunits((prev) => {
        const found = prev.find((s) => s.name === data.subunit);
        if (found) {
          return prev.map((s) =>
            s.name === data.subunit ? { ...s, status: "running" as const } : s
          );
        }
        return [
          ...prev,
          { name: data.subunit, specCount: data.specCount, status: "running" as const },
        ];
      });
    }
    if (data.type === "subunitComplete") {
      setSubunits((prev) =>
        prev.map((s) =>
          s.name === data.subunit
            ? { ...s, status: "done" as const, mapped: data.mapped, partial: data.partial }
            : s
        )
      );
    }
    if (data.type === "tokens") {
      setTokens(data.total);
    }
  };

  const handleRun = (dryRun = false) => {
    setPanelState("running");
    setStreamLines([]);
    setSubunits([]);
    setElapsed(0);
    setTokens(0);
    setErrorMsg("");
    setResults(null);
    postMessage({
      type: "runMap",
      options: {
        designSpecPath: designSpec,
        codebaseDir,
        projectContextPath: projectContext || undefined,
        skipMapped,
        maxSpecsPerSubunit: maxPerSubunit,
        minConfidenceThreshold: minConfidence,
        extraInstructions: extraInstructions || undefined,
        dryRun,
      },
    });
  };

  const handleCancel = () => {
    postMessage({ type: "cancelRun" });
    setPanelState("idle");
  };

  const handleRetry = (resolutions: ManualResolution[]) => {
    postMessage({ type: "resolveItems", resolutions });
    // Re-trigger the run (the extension re-runs with the resolution context)
    handleRun();
  };

  const browse = (field: string, isDir: boolean) => {
    postMessage(isDir ? { type: "browseDir", field } : { type: "browseFile", field });
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="panel">
      <div className="panel-header">
        <h2 className="panel-title">PIKA · Map Command</h2>
        {panelState !== "idle" && (
          <span className={`panel-badge panel-badge--${panelState}`}>
            {panelState === "running" ? "Running…" : panelState}
          </span>
        )}
      </div>

      {/* Inputs — always visible */}
      <Section title="Inputs">
        <FileField
          label="Design Spec"
          value={designSpec}
          field="designSpec"
          onChange={setDesignSpec}
          onBrowse={browse}
        />
        <FileField
          label="Codebase Dir"
          value={codebaseDir}
          field="codebaseDir"
          isDir
          onChange={setCodebaseDir}
          onBrowse={browse}
        />
        <FileField
          label="Project Context"
          value={projectContext}
          field="projectContext"
          optional
          onChange={setProjectContext}
          onBrowse={browse}
        />
      </Section>

      <Section title="Options" collapsible defaultOpen>
        <CheckboxField
          label="Skip already-mapped specs"
          checked={skipMapped}
          onChange={setSkipMapped}
        />
        <NumberField
          label="Max specs per subunit"
          value={maxPerSubunit}
          min={1}
          max={100}
          onChange={setMaxPerSubunit}
        />
        <NumberField
          label="Min confidence threshold"
          value={minConfidence}
          min={0}
          max={1}
          step={0.05}
          onChange={setMinConfidence}
        />
        <TextAreaField
          label="Extra instructions"
          value={extraInstructions}
          placeholder="Additional guidance for the mapping agent…"
          optional
          onChange={setExtraInstructions}
        />
      </Section>

      {worksetCount !== null && (
        <div className="workset-preview">
          {worksetCount} spec(s) pending (unmapped / partial)
        </div>
      )}

      {/* Action buttons */}
      {panelState === "idle" || panelState === "complete" || panelState === "failed" ? (
        <div className="action-row">
          <button
            className="btn btn--primary"
            onClick={() => handleRun(false)}
            disabled={!designSpec}
          >
            ▶ Run Map
          </button>
          <button
            className="btn btn--secondary"
            onClick={() => handleRun(true)}
            disabled={!designSpec}
          >
            ⊡ Dry Run
          </button>
        </div>
      ) : null}

      {/* Error banner */}
      {panelState === "failed" && (
        <div className="error-banner">✗ {errorMsg}</div>
      )}

      {/* Progress */}
      {panelState === "running" && (
        <MapProgress
          subunits={subunits}
          streamLines={streamLines}
          elapsed={elapsed}
          tokens={tokens}
          onCancel={handleCancel}
        />
      )}

      {/* Manual resolution */}
      {panelState === "blocked" && (
        <ManualResolutionBlock items={manualItems} onRetry={handleRetry} />
      )}

      {/* Results */}
      {panelState === "complete" && results && (
        <MapResultsView
          results={results}
          onOpenFile={(p) => postMessage({ type: "openFile", path: p })}
          onRerunUnmapped={() => handleRun(false)}
        />
      )}
    </div>
  );
}
