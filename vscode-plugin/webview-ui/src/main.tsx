import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

declare global {
  interface Window {
    acquireVsCodeApi: () => { postMessage: (message: unknown) => void };
  }
}

const vscode = window.acquireVsCodeApi();
const rootContainer = document.getElementById("root");

if (!rootContainer) {
  throw new Error("Unable to find #root container for webview app.");
}

const root = createRoot(rootContainer);
root.render(<App postMessage={(message) => vscode.postMessage(message)} />);
