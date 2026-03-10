import { afterEach, describe, expect, it, vi } from "vitest";
import { waitForMockMappingDelay } from "../src/core/mappingRuntime";

afterEach(() => {
  vi.useRealTimers();
});

describe("waitForMockMappingDelay", () => {
  it("resolves only after configured delay", async () => {
    vi.useFakeTimers();
    let resolved = false;
    const promise = waitForMockMappingDelay(300).then(() => {
      resolved = true;
    });

    await vi.advanceTimersByTimeAsync(299);
    expect(resolved).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    await promise;
    expect(resolved).toBe(true);
  });
});
