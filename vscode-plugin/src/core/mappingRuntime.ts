export const MOCK_MAPPING_EXEC_DELAY_MS = 5000;

/**
 * Adds a fixed async delay to simulate mapping execution work.
 * @param delayMs Delay duration in milliseconds.
 */
export function waitForMockMappingDelay(delayMs = MOCK_MAPPING_EXEC_DELAY_MS): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, delayMs);
  });
}
