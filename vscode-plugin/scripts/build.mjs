import { build, context } from "esbuild";

const isWatch = process.argv.includes("--watch");

/**
 * Creates esbuild options for extension-host bundle.
 * @returns {import("esbuild").BuildOptions}
 */
function createExtensionBuildOptions() {
  return {
    entryPoints: ["src/extension.ts"],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    outfile: "dist/extension.js",
    external: ["vscode"],
    sourcemap: true,
    logLevel: "info",
  };
}

/**
 * Creates esbuild options for webview React bundle.
 * @returns {import("esbuild").BuildOptions}
 */
function createWebviewBuildOptions() {
  return {
    entryPoints: ["webview-ui/src/main.tsx"],
    bundle: true,
    format: "iife",
    platform: "browser",
    target: "es2020",
    outfile: "dist/webview.js",
    sourcemap: true,
    logLevel: "info",
    loader: {
      ".css": "css",
    },
  };
}

/**
 * Runs one-shot build or watch mode for both bundles.
 * @returns {Promise<void>}
 */
async function runBuild() {
  const extensionOptions = createExtensionBuildOptions();
  const webviewOptions = createWebviewBuildOptions();

  if (isWatch) {
    const extensionCtx = await context(extensionOptions);
    const webviewCtx = await context(webviewOptions);
    await Promise.all([extensionCtx.watch(), webviewCtx.watch()]);
    console.log("Watching extension and webview bundles...");
    void extensionCtx;
    void webviewCtx;
    return;
  }

  await Promise.all([build(extensionOptions), build(webviewOptions)]);
}

runBuild().catch((error) => {
  console.error(error);
  process.exit(1);
});
