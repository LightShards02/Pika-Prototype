import * as path from "path";

export interface CodexValidationResult {
  passed: boolean;
  message: string;
}

export const MOCK_CODEX_VALIDATION_STEP_DELAY_MS = 800;

/**
 * Runs a stubbed handshake validation flow for the selected executable.
 * @param executablePath Effective executable path selected by runtime detection.
 * @param onProgress Callback used to surface real-time validation status.
 */
export async function validateCodexExecutableHandshake(
  executablePath: string,
  onProgress?: (message: string) => void,
): Promise<CodexValidationResult> {
  const fileName = path.basename(executablePath);
  const steps = [
    "Starting Codex validation...",
    `Checking executable (${fileName})...`,
    "Running handshake stub...",
  ];

  for (const step of steps) {
    onProgress?.(step);
    await waitForValidationStepDelay();
  }

  return {
    passed: true,
    message: "Codex validation passed. Agent is ready.",
  };
}

/**
 * Adds fixed delay between validation progress updates for UI visibility.
 * @param delayMs Delay in milliseconds.
 */
export function waitForValidationStepDelay(delayMs = MOCK_CODEX_VALIDATION_STEP_DELAY_MS): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, delayMs);
  });
}
