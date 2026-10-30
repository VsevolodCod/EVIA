import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import type { Profile, Source, SourceSchema } from "../../api";
import type { Entry } from "../chat/types";
import { ReportBuilder } from "./ReportBuilder";

const source: Source = {
  source_id: "sales", name: "Продажи", source_type: "csv", status: "available",
  created_at: "2026-10-29T12:00:00Z", schema_version: 2, snapshot_id: "snapshot-2",
  import_report: { sha256: "a".repeat(64), size_bytes: 100, encoding: "utf-8",
    delimiter: ",", rows_read: 3, accepted_rows: 2, rejected_rows: 1,
    blank_lines: 0, warnings: ["Строка 3 пропущена"], errors: [] },
};
const schema: SourceSchema = { source_id: "sales", version: 2, objects: [{
  object_id: "sales:table", name: "sales", object_type: "csv_table", row_count: 2,
  fields: [
    { name: "month", inferred_type: "string", nullable: false, is_identifier_candidate: false },
    { name: "revenue", inferred_type: "number", nullable: true, is_identifier_candidate: false },
  ],
}] };
const profile: Profile = { coverage: "full", sample_size: 2, sample_limit: 500,
  processed_rows: 2, snapshot_id: "snapshot-2", note: "", columns: {
    month: { sample_non_null_count: 2, sample_null_count: 0, distinct_sample_values: 2,
      top_values: [], non_null_count: 2, null_count: 0, empty_count: 0,
      distinct_count: 2, uniqueness_ratio: 1, is_identifier_candidate: false,
      top_values_coverage: "sample" },
    revenue: { sample_non_null_count: 1, sample_null_count: 1, distinct_sample_values: 1,
      top_values: [], non_null_count: 1, null_count: 1, empty_count: 0,
      distinct_count: 1, uniqueness_ratio: 1, is_identifier_candidate: false,
      top_values_coverage: "sample" },
  } };
const calculation: Entry = { id: "answer-1", question: "Какая выручка?", state: "success",
  answer: { answer: "Выручка составила 120.", steps: 1,
    analysis: { intent: "sum", sql: "SELECT SUM(revenue) FROM sales", explanation: "Сумма" },
    tool_results: [{ tool_name: "query_data", ok: true, data: {
      columns: [{ name: "total" }], rows: [[120]], truncated: false,
      provenance: [{ internal_path: "/secret/private.csv" }],
    } }],
  } };

it("builds a source report with schema, sample, quality scope and import issues", () => {
  render(<ReportBuilder source={source} schema={schema} rows={[{ month: "Янв", revenue: 120 }, { month: "Фев", revenue: null }]}
    profile={profile} entries={[calculation]} onClose={() => undefined} />);
  const report = screen.getByRole("article", { name: "PDF-отчёт" });
  expect(within(report).getByText("Продажи")).toBeInTheDocument();
  expect(within(report).getByText("Янв")).toBeInTheDocument();
  expect(within(report).getByText(/revenue: 1 пропуск/)).toBeInTheDocument();
  expect(within(report).getAllByText(/Весь источник/).length).toBeGreaterThan(0);
  expect(within(report).getByText(/Отклонено строк при импорте: 1/)).toBeInTheDocument();
  expect(within(report).queryByText("Какая выручка?")).not.toBeInTheDocument();
});

it("adds selected AI calculations to the report and prints without private tool metadata", () => {
  const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
  const oldTitle = document.title;
  render(<ReportBuilder source={source} schema={schema} rows={[{ month: "Янв", revenue: 120 }]}
    profile={profile} entries={[calculation, { id: "error", question: "Сбой", state: "error" }]}
    onClose={() => undefined} />);
  expect(screen.queryByRole("checkbox", { name: /Сбой/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: /Какая выручка/ }));
  const report = screen.getByRole("article", { name: "PDF-отчёт" });
  expect(within(report).getByRole("heading", { name: /Какая выручка/ })).toBeInTheDocument();
  expect(within(report).getByText("Выручка составила 120.")).toBeInTheDocument();
  expect(within(report).getByText("SELECT SUM(revenue) FROM sales")).toBeInTheDocument();
  expect(within(report).getAllByText("120").length).toBeGreaterThan(0);
  expect(report).not.toHaveTextContent("/secret/private.csv");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить в PDF" }));
  expect(print).toHaveBeenCalledOnce();
  expect(document.title).toContain("Продажи");
  window.dispatchEvent(new Event("afterprint"));
  expect(document.title).toBe(oldTitle);
  print.mockRestore();
});
