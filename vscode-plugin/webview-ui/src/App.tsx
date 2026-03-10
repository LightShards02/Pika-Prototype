import React, { useEffect, useMemo, useState } from "react";
import {
  CodexRuntimePayload,
  CodeReference,
  CursorContextMapping,
  ExtensionStatePayload,
  SpecCodeMapping,
  WebviewIncomingMessage,
} from "./types";

interface AppProps {
  postMessage: (message: {
    type:
      | "chooseDesignSpec"
      | "requestCodeMapping"
      | "refreshMappings"
      | "openCodeReference"
      | "configureCodexPath";
    payload?: CodeReference;
  }) => void;
}

const DEFAULT_CODEX_RUNTIME: CodexRuntimePayload = {
  status: "missing",
  source: "none",
  message: "Codex executable status is still being resolved.",
};

/**
 * Renders the design-spec import, preview, and bidirectional mapping UI.
 */
export function App({ postMessage }: AppProps): React.ReactElement {
  const [statePayload, setStatePayload] = useState<ExtensionStatePayload>({
    rows: [],
    specToCodeMappings: [],
    codexRuntime: DEFAULT_CODEX_RUNTIME,
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

  return (
    <div className="app">
      <header className="toolbar">
        <h2>Design Spec Mapper (MVP)</h2>
        <div className="actions">
          <button
            type="button"
            className="icon-button"
            title="Import design spec CSV"
            aria-label="Import design spec CSV"
            onClick={() => postMessage({ type: "chooseDesignSpec" })}
          >
            ⭱
          </button>
          <button
            type="button"
            className="icon-button"
            title="Refresh mappings and preview file"
            aria-label="Refresh mappings"
            onClick={() => postMessage({ type: "refreshMappings" })}
          >
            ↻
          </button>
        </div>
      </header>

      <section className="status">
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
        {!codexReady ? (
          <button
            type="button"
            className="secondary-button"
            onClick={() => postMessage({ type: "configureCodexPath" })}
          >
            Configure Codex Path
          </button>
        ) : null}
        <div>
          <strong>Imported CSV:</strong> {statePayload.importedFilePath ?? "Not imported yet"}
        </div>
        <div>
          <strong>Spec tab file:</strong> {statePayload.importedPreviewPath ?? "Not generated yet"}
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
