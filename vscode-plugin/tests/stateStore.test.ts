import { describe, expect, it } from "vitest";
import { StateStore } from "../src/core/stateStore";

describe("StateStore", () => {
  it("hydrates lastMappedAt from constructor options", () => {
    const store = new StateStore({ lastMappedAt: 1741866660000 });
    expect(store.getState().lastMappedAt).toBe(1741866660000);
  });

  it("preserves lastMappedAt when imported data is replaced", () => {
    const store = new StateStore({ lastMappedAt: 1741866660000 });
    store.setImportedData({
      importedFilePath: "/tmp/spec.csv",
      importedPreviewPath: "/tmp/spec.md",
      rows: [],
      specToCodeMappings: [],
    });
    expect(store.getState().lastMappedAt).toBe(1741866660000);
  });

  it("updates lastMappedAt through setter", () => {
    const store = new StateStore();
    store.setLastMappedAt(1741866720000);
    expect(store.getState().lastMappedAt).toBe(1741866720000);
  });
});
