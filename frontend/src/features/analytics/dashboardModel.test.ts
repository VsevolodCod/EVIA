import { describe, expect, it } from "vitest";
import type { SourceSchema } from "../../api";
import { buildDashboardModel } from "./dashboardModel";

const schema: SourceSchema = {
  source_id: "sales",
  version: 1,
  objects: [{
    object_id: "sales:table",
    name: "sales",
    object_type: "csv_table",
    row_count: 4,
    fields: [
      { name: "id", inferred_type: "integer", nullable: false, is_identifier_candidate: true },
      { name: "region", inferred_type: "string", nullable: true, is_identifier_candidate: false },
      { name: "revenue", inferred_type: "number", nullable: false, is_identifier_candidate: false },
      { name: "created_at", inferred_type: "date", nullable: false, is_identifier_candidate: false },
    ],
  }],
};

describe("buildDashboardModel", () => {
  it("builds only factual summaries and excludes identifier candidates", () => {
    const model = buildDashboardModel(schema, [
      { id: 1, region: "Север", revenue: 100, created_at: "2026-01-02" },
      { id: 2, region: "Юг", revenue: 200, created_at: "2026-01-02" },
      { id: 3, region: "Север", revenue: 300, created_at: "2026-02-01" },
      { id: 4, region: null, revenue: 400, created_at: "2026-02-01" },
    ]);

    expect(model.rowCount).toBe(4);
    expect(model.completeness).toBe(93.75);
    expect(model.numeric).toMatchObject({ field: "revenue", mean: 250, min: 100, max: 400 });
    expect(model.category).toEqual({
      field: "region",
      values: [{ label: "Север", value: 2 }, { label: "Юг", value: 1 }],
    });
    expect(model.timeline).toEqual({
      field: "created_at",
      values: [{ label: "02.01.2026", value: 2 }, { label: "01.02.2026", value: 2 }],
    });
    expect(model.numeric?.field).not.toBe("id");
  });

  it("does not fabricate charts when rows have no usable dimensions", () => {
    const empty = buildDashboardModel({ ...schema, objects: [{ ...schema.objects[0], fields: [schema.objects[0].fields[0]] }] }, [
      { id: 1 }, { id: 2 }, { id: 3 },
    ]);

    expect(empty.numeric).toBeNull();
    expect(empty.category).toBeNull();
    expect(empty.timeline).toBeNull();
    expect(empty.completeness).toBe(100);
  });

  it("sorts dates chronologically and ignores invalid values instead of inventing a timeline", () => {
    const model = buildDashboardModel(schema, [
      { revenue: 10, created_at: "2026-10-01" },
      { revenue: 20, created_at: "not-a-date" },
      { revenue: 30, created_at: "2026-02-01" },
    ]);

    expect(model.timeline?.values.map((value) => value.label)).toEqual(["01.02.2026", "01.10.2026"]);
  });
});
