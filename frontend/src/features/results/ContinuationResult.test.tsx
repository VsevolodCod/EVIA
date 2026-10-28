import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ToolResults } from "./ToolResults";

it("opens a continued result in the requested view and retains its CSV export", () => {
  render(<ToolResults results={[{ tool_name: "continue_analysis", ok: true, data: {
    presentation: "bar", reused_result: true, query_result: {
      result_id: "r1", columns: [{ name: "month", data_type: "date" }, { name: "total", data_type: "integer" }],
      rows: [["2025-01-01", 30], ["2025-02-01", 40]], returned_rows: 2, row_limit: 1000, truncated: false,
    },
  } }]} />);
  expect(screen.getByRole("button", { name: "Столбцы" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("img", { name: /Столбчатый график/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Скачать CSV" })).toBeInTheDocument();
  expect(screen.getByLabelText("2025-01-01: 30")).toBeInTheDocument();
});
