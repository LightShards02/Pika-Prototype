import React, { useEffect, useMemo, useState } from "react";
import {
  CodexValidationRuntimePayload,
  CodexRuntimePayload,
  CodeReference,
  CursorContextMapping,
  ExtensionStatePayload,
  ImportedDocumentOpenPayload,
  MappingRuntimePayload,
  SpecCodeMapping,
  WebviewIncomingMessage,
} from "./types";

interface AppProps {
  postMessage: (message: {
    type:
      | "chooseDesignSpec"
      | "chooseIssueTracker"
      | "chooseTestingPlan"
      | "requestCodeMapping"
      | "refreshMappings"
      | "openCodeReference"
      | "openImportedDocument"
      | "configureCodexPath"
      | "configureCodeDirectory";
    payload?: CodeReference | ImportedDocumentOpenPayload;
  }) => void;
}

const DEFAULT_CODEX_RUNTIME: CodexRuntimePayload = {
  status: "missing",
  source: "none",
  message: "Codex executable status is still being resolved.",
};

const DEFAULT_MAPPING_RUNTIME: MappingRuntimePayload = {
  isRunning: false,
  message: "Idle",
};

const DEFAULT_CODEX_VALIDATION_RUNTIME: CodexValidationRuntimePayload = {
  isValidating: false,
  message: "",
};

/**
 * Renders the design-spec import, preview, and bidirectional mapping UI.
 */
export function App({ postMessage }: AppProps): React.ReactElement {
  const [statePayload, setStatePayload] = useState<ExtensionStatePayload>({
    rows: [],
    specToCodeMappings: [],
    codexRuntime: DEFAULT_CODEX_RUNTIME,
    codexValidationRuntime: DEFAULT_CODEX_VALIDATION_RUNTIME,
    mappingRuntime: DEFAULT_MAPPING_RUNTIME,
  });
  const [cursorContext, setCursorContext] = useState<CursorContextMapping>({
    filePath: "",
    symbolName: "",
    symbolKind: "unknown",
    matchedSpecs: [],
    source: "placeholder",
    message: "Move cursor into a function or class to view mapped specs.",
  });
  const [error, setError] = useState<string>("");

  useEffect(() => {
    const onMessage = (event: MessageEvent<WebviewIncomingMessage>) => {
      const message = event.data;
      if (message.type === "stateUpdated" && message.payload) {
        const payload = message.payload as ExtensionStatePayload;
        setStatePayload({
          ...payload,
          codexRuntime: payload.codexRuntime ?? DEFAULT_CODEX_RUNTIME,
          codexValidationRuntime:
            payload.codexValidationRuntime ?? DEFAULT_CODEX_VALIDATION_RUNTIME,
          mappingRuntime: payload.mappingRuntime ?? DEFAULT_MAPPING_RUNTIME,
        });
        setError("");
      } else if (message.type === "cursorContextUpdated" && message.payload) {
        setCursorContext(message.payload as CursorContextMapping);
      } else if (message.type === "error") {
        setError(message.message ?? "Unexpected extension error.");
      }
    };

    window.addEventListener("message", onMessage);
    postMessage({ type: "requestCodeMapping" });
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [postMessage]);

  const mappingBySpecId = useMemo(() => {
    const map = new Map<string, SpecCodeMapping>();
    for (const mapping of statePayload.specToCodeMappings) {
      map.set(mapping.specId, mapping);
    }
    return map;
  }, [statePayload.specToCodeMappings]);
  const codexReady = statePayload.codexRuntime.status === "ready";
  const mappingRunning = statePayload.mappingRuntime.isRunning;
  const documentRows = [
    {
      id: "designSpec" as const,
      title: "Design Spec",
      path: statePayload.importedFilePath,
      importMessageType: "chooseDesignSpec" as const,
      importDisabled: mappingRunning,
    },
    {
      id: "issueTracker" as const,
      title: "Issue Tracking Sheet",
      path: statePayload.issueTrackerFilePath,
      importMessageType: "chooseIssueTracker" as const,
      importDisabled: false,
    },
    {
      id: "testingPlan" as const,
      title: "Testing Plan",
      path: statePayload.testingPlanFilePath,
      importMessageType: "chooseTestingPlan" as const,
      importDisabled: false,
    },
  ];

  return (
    <div className="app">
      <header className="toolbar">
        <h2>Design Spec Mapper (MVP)</h2>
        <div className="actions">
          <button
            type="button"
            className="icon-button"
            title="Refresh mappings and preview file"
            aria-label="Refresh mappings"
            disabled={mappingRunning || !codexReady}
            onClick={() => postMessage({ type: "refreshMappings" })}
          >
            ↻
          </button>
        </div>
      </header>

      <section className="document-column">
        <h3>Documents</h3>
        {documentRows.map((row) => (
          <div className="document-row" key={row.id}>
            <button
              type="button"
              className={`document-bar ${row.path ? "imported" : "empty"}`}
              title={row.path ? `Double-click to quick-open ${row.title}` : `${row.title} is not imported yet`}
              onDoubleClick={() =>
                postMessage({
                  type: "openImportedDocument",
                  payload: { documentType: row.id },
                })
              }
            >
              <span className="document-title">{row.title}</span>
              <span className="document-path">{row.path ?? "Not imported"}</span>
            </button>
            <button
              type="button"
              className="secondary-button document-import-button"
              disabled={row.importDisabled}
              onClick={() => postMessage({ type: row.importMessageType })}
            >
              Import
            </button>
          </div>
        ))}
        <p className="document-hint">Double-click a document bar to quick-open the imported file.</p>
      </section>

      <section className="status">
        <div className="mapping-status-row">
          <strong>Mapping status:</strong>
          <span className={`mapping-badge ${mappingRunning ? "running" : "idle"}`}>
            {mappingRunning ? "Running..." : "Idle"}
          </span>
        </div>
        <div>
          <strong>Mapping details:</strong> {statePayload.mappingRuntime.message}
        </div>
        {statePayload.codexValidationRuntime.isValidating ? (
          <div className="validation-status">
            <strong>Validation:</strong> {statePayload.codexValidationRuntime.message}
          </div>
        ) : null}
        <div className="codex-status-row">
          <strong>Agent readiness:</strong>
          <span className={`codex-badge ${codexReady ? "ready" : "missing"}`}>
            {codexReady ? "Ready" : "Not ready"}
          </span>
        </div>
        <div>
          <strong>Codex executable:</strong> {statePayload.codexRuntime.effectivePath ?? "Not detected"}
        </div>
        <div>
          <strong>Codex details:</strong> {statePayload.codexRuntime.message}
        </div>
        <button
          type="button"
          className="secondary-button"
          disabled={statePayload.codexValidationRuntime.isValidating}
          onClick={() => postMessage({ type: "configureCodexPath" })}
        >
          Configure Codex Path
        </button>
        <div>
          <strong>Code directory:</strong> {statePayload.codeDirectoryPath ?? "Not resolved"}
        </div>
        <button
          type="button"
          className="secondary-button"
          disabled={mappingRunning}
          onClick={() => postMessage({ type: "configureCodeDirectory" })}
        >
          Configure Code Directory
        </button>
        <div>
          <strong>Spec preview tab:</strong> {statePayload.importedPreviewPath ?? "Not generated yet"}
        </div>
        {error ? <div className="error">Error: {error}</div> : null}
      </section>

      <section className="panel">
        <h3>Real-time Cursor Mapping</h3>
        {!cursorContext.symbolName ? (
          <p className="empty">
            {cursorContext.message ?? "Move cursor into a function or class to view mapped specs."}
          </p>
        ) : (
          <>
            <div className="code-file">
              <strong>Current {cursorContext.symbolKind}:</strong> {cursorContext.symbolName}
            </div>
            {cursorContext.matchedSpecs.length === 0 ? (
              <p className="empty">{cursorContext.message ?? "No specs mapped to the current symbol."}</p>
            ) : (
              <ul className="mapping-list">
                {cursorContext.matchedSpecs.map((match) => (
                  <li key={`${cursorContext.filePath}-${cursorContext.symbolName}-${match.specId}`}>
                    <span className="spec-id">{match.specId}</span>
                    <span className="meta">confidence={match.confidence}</span>
                    <div className="spec-content">
                      <div>
                        <strong>Title:</strong> {match.title}
                      </div>
                      <div>
                        <strong>Requirement:</strong> {match.requirement || "N/A"}
                      </div>
                      <div>
                        <strong>Acceptance:</strong> {match.acceptanceCriteria || "N/A"}
                      </div>
                      <div>
                        <strong>Mapped Function/Class:</strong>{" "}
                        {(() => {
                          const rowMapping = mappingBySpecId.get(match.specId);
                          const firstReference: CodeReference | undefined = rowMapping?.references?.[0];
                          if (!firstReference) {
                            return "N/A";
                          }
                          return (
                            <a
                              href="#"
                              onClick={(event) => {
                                event.preventDefault();
                                postMessage({ type: "openCodeReference", payload: firstReference });
                              }}
                            >
                              {`${firstReference.filePath.split("/")[firstReference.filePath.split("/").length - 1] ?? firstReference.filePath}/${firstReference.symbol}`}
                            </a>
                          );
                        })()}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  );
}
