import { describe, expect, it } from "vitest";
import { parseDesignSpecCsv } from "../src/core/csvParser";

describe("parseDesignSpecCsv", () => {
  it("parses expected design-spec columns", () => {
    const csv = [
      "spec_id,title,requirement,acceptance_criteria,status",
      "DS-1,Login,User can login,Token issued,approved",
      "DS-2,History,User can view history,History loads,draft",
    ].join("\n");

    const rows = parseDesignSpecCsv(csv);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      id: "DS-1",
      title: "Login",
      requirement: "User can login",
      acceptanceCriteria: "Token issued",
      status: "approved",
    });
    expect(rows[1].id).toBe("DS-2");
  });

  it("falls back when required columns are missing", () => {
    const csv = [
      "name,notes",
      "Simple row,Some text",
    ].join("\n");

    const rows = parseDesignSpecCsv(csv);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("ROW_1");
    expect(rows[0].title).toBe("Simple row");
    expect(rows[0].status).toBe("draft");
  });
});
