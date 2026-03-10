# Design Spec Mapper MVP (VS Code + React)

This extension is an MVP that demonstrates a bidirectional traceability UI:

1. **Design spec import** from CSV.
2. **Design spec table preview** in a React webview and a generated markdown file tab.
3. **Design spec -> code mapping** shown in the preview table with hyperlinks to code symbols.
4. **Code -> design spec mapping** shown for active code files.
5. **Real-time cursor mapping** (function/class under cursor -> spec IDs and spec contents).

## Important MVP Note

The mapping algorithm is intentionally a **placeholder**. The extension currently uses deterministic **dummy mapping data** with lightweight keyword heuristics.

## Run locally

1. Install dependencies:
   - `npm install`
2. Build extension + webview:
   - `npm run build`
3. Open this folder in VS Code and press `F5` to launch Extension Development Host.
4. Open the **Design Spec Mapper** activity bar icon.
5. Click **Import Design Spec CSV** and select a CSV file.
6. Use the icon-only toolbar buttons:
   - `⭱` import design spec
   - `↻` refresh placeholder mappings and regenerate preview file tab

## CSV expectations

The parser accepts flexible headers. Preferred headers are:

- `spec_id`
- `title`
- `requirement`
- `acceptance_criteria`
- `status`

If some columns are missing, the extension falls back to generated row IDs and defaults.
