import * as vscode from "vscode";

/**
 * Builds static HTML for the React-based webview app.
 * @param webview VS Code webview API.
 * @param extensionUri Extension root URI.
 */
export function getWebviewHtml(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "dist", "webview.js"));
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, "dist", "webview.css"));
  const styleNonce = String(Date.now());
  const scriptNonce = String(Date.now() + 1);

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src ${webview.cspSource} https:; style-src ${webview.cspSource} 'nonce-${styleNonce}'; script-src 'nonce-${scriptNonce}';"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Design Spec Mapper</title>
    <link rel="stylesheet" href="${styleUri}" />
    <style nonce="${styleNonce}">
      html, body, #root {
        margin: 0;
        height: 100%;
        width: 100%;
      }
      body {
        font-family: var(--vscode-font-family);
        color: var(--vscode-editor-foreground);
        background: var(--vscode-editor-background);
      }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script nonce="${scriptNonce}">
      window.__DESIGN_SPEC_MAPPER_BOOTSTRAP__ = {};
    </script>
    <script nonce="${scriptNonce}" src="${scriptUri}"></script>
  </body>
</html>`;
}
