import { csvTableFrom, serializeCsv } from "./csvExport";

it("exports only returned cells, including Unicode and empty results", () => {
  const table = csvTableFrom({
    columns: [{ name: "город" }, { name: "значение" }],
    rows: [["Томск", null], ["Омск", "a,\"b\nв"]],
    truncated: true,
    provenance: [{ internal_path: "/private/secrets/token" }],
  });

  expect(table).toEqual({ columns: ["город", "значение"], rows: [["Томск", null], ["Омск", "a,\"b\nв"]], truncated: true });
  expect(serializeCsv(table!)).toBe('\uFEFF"город","значение"\r\n"Томск",""\r\n"Омск","a,""b\nв"""\r\n');
  expect(serializeCsv({ columns: ["город"], rows: [], truncated: false })).toBe('\uFEFF"город"\r\n');
});

it("neutralizes spreadsheet formulas even after leading whitespace and control characters", () => {
  const csv = serializeCsv({
    columns: ["value"],
    rows: [["=1+1"], [" +SUM(A1)"], ["\t@cmd"], ["-2"], ["обычный текст"], [-2]],
    truncated: false,
  });

  expect(csv).toContain('"\'=1+1"');
  expect(csv).toContain('"\' +SUM(A1)"');
  expect(csv).toContain('"\'\t@cmd"');
  expect(csv).toContain('"\'-2"');
  expect(csv).toContain('"обычный текст"');
  expect(csv).toContain('"-2"');
});
