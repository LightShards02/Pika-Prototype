import * as vscode from "vscode";
import * as crypto from "crypto";

/**
 * Returns the CSP-safe HTML shell used by both the sidebar webview and the
 * command panel webviews.  The bootstrap object carries the initial view
 * context so the React app knows which component to render.
 *
 * @param webview   VS Code webview API handle.
 * @param extUri    Extension root URI.
 * @param bootstrap Arbitrary JSON object injected as `window.__PIKA__`.
 */
export function getWebviewHtml(
  webview: vscode.Webview,
  extUri: vscode.Uri,
  bootstrap: Record<string, unknown> = {}
): string {
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extUri, "dist", "webview.js"));
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extUri, "dist", "webview.css"));

  // Use a fresh nonce per call so the CSP is tight.
  const nonce = crypto.randomBytes(16).toString("hex");

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src ${webview.cspSource} https:; style-src ${webview.cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PIKA</title>
    <link rel="stylesheet" href="${styleUri}" nonce="${nonce}" />
    <style nonce="${nonce}">
      html, body, #root {
        margin: 0;
        padding: 0;
        height: 100%;
        width: 100%;
        overflow: hidden;
      }
      body {
        font-family: var(--vscode-font-family);
        font-size: var(--vscode-font-size);
        color: var(--vscode-editor-foreground);
        background: var(--vscode-editor-background);
      }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script nonce="${nonce}">
      window.__PIKA__ = ${JSON.stringify(bootstrap)};
    </script>
    <script nonce="${nonce}" src="${scriptUri}"></script>
  </body>
</html>`;
}
