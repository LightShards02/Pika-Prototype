import { afterEach, describe, expect, it, vi } from "vitest";
import { validateCodexExecutableHandshake } from "../src/core/codexValidation";

afterEach(() => {
  vi.useRealTimers();
});

describe("validateCodexExecutableHandshake", () => {
  it("emits ordered progress updates and returns pass result", async () => {
    vi.useFakeTimers();
    const progressMessages: string[] = [];
    const promise = validateCodexExecutableHandshake("/tmp/codex-demo/codex", (message) => {
      progressMessages.push(message);
    });

    await vi.runAllTimersAsync();
    const result = await promise;

    expect(progressMessages).toEqual([
      "Starting Codex validation...",
      "Checking executable (codex)...",
      "Running handshake stub...",
    ]);
    expect(result.passed).toBe(true);
    expect(result.message).toContain("Agent is ready");
  });
});
