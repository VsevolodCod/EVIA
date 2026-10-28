import { chartFields, chartNumber } from "./resultChartModel";

it("excludes identifier names, padded codes and explicitly marked identifiers", () => {
  const rows = [{ customerId: 10, "Код клиента": 20, segment: "001", customKey: 30, reference: 40, amount: "1.25" }];
  expect(chartFields(rows, [{ name: "reference", is_identifier_candidate: true }]).measures).toEqual(["amount"]);
});

it("does not treat booleans, dates, mixed text, infinity or blanks as measures", () => {
  expect(chartFields([
    { active: true, date: "2026-01-01", mixed: "10", blank: " ", endless: Infinity },
    { active: false, date: "2026-02-01", mixed: "unknown", blank: null, endless: Infinity },
  ]).measures).toEqual([]);
  expect(chartNumber("1e3")).toBe(1000);
  expect(chartNumber("2,50")).toBe(2.5);
  expect(chartNumber("0x10")).toBeNull();
});
