import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { ToolResults } from "./ToolResults";

const result = [{
  tool_name: "run_sql",
  ok: true,
  data: [
    { month: "Янв", revenue: 120 },
    { month: "Фев", revenue: 180 },
    { month: "Мар", revenue: 150 },
  ],
}];

it("switches one factual result between a table and local chart types", () => {
  render(<ToolResults results={result} />);

  expect(screen.getByRole("region", { name: "Результат run_sql" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Столбцы" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Линия" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getByRole("img", { name: "Столбчатый график: revenue по month" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Результат run_sql" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  expect(screen.getByRole("img", { name: "Линейный график: revenue по month" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Таблица" }));
  expect(screen.getByRole("region", { name: "Результат run_sql" })).toBeInTheDocument();
});

it("keeps the table and explains why a chart is unavailable", () => {
  render(<ToolResults results={[{ tool_name: "run_sql", ok: true, data: [{ city: "Томск" }, { city: "Омск" }] }]} />);

  expect(screen.getByRole("region", { name: "Результат run_sql" })).toBeInTheDocument();
  expect(screen.getByText("Для графика нужен числовой показатель и поле для подписей.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Столбцы" })).not.toBeInTheDocument();
});

it("offers export for returned SQL rows and labels a truncated result", () => {
  render(<ToolResults results={[{
    tool_name: "query_data", ok: true,
    data: { columns: [{ name: "city" }], rows: [["Томск"]], truncated: true, provenance: [{ internal_path: "/private/data.csv" }] },
  }]} />);

  expect(screen.getByRole("button", { name: "Скачать CSV" })).toBeInTheDocument();
  expect(screen.getByText(/только 1 строка, возвращённая сервером/)).toBeInTheDocument();
});

it("does not export source metadata or failed results", () => {
  render(<ToolResults results={[
    { tool_name: "list_sources", ok: true, data: [{ source_id: "abc" }] },
    { tool_name: "query_data", ok: false, data: { columns: [{ name: "secret" }], rows: [["value"]] } },
  ]} />);

  expect(screen.queryByRole("button", { name: "Скачать CSV" })).not.toBeInTheDocument();
});

it("compacts long source identifiers and copies their full values", async () => {
  const sourceId = "74d109616b5643879e835a4be759340a";
  const snapshotId = "0aa1d461e0984b9295f6c2a9f6109c8a";
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

  render(<ToolResults results={[{
    tool_name: "list_sources",
    ok: true,
    data: [{ source_id: sourceId, snapshot_id: snapshotId, name: "Продажи" }],
  }]} />);

  expect(screen.getByText("74d10961…59340a")).toBeInTheDocument();
  expect(screen.getByText("0aa1d461…109c8a")).toBeInTheDocument();
  expect(screen.getByTitle(sourceId)).toBeInTheDocument();
  expect(screen.getByTitle(snapshotId)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Скопировать полный source_id" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(sourceId));
});

it("shows hypothesis evidence in readable cards instead of raw JSON", () => {
  render(<ToolResults results={[{ tool_name: "compare_groups", ok: true, data: {
    statement: "Сравнение продаж",
    results: [{ id: "comparison", method: "compare", status: "completed", error: null,
      data: { left: { label: "До", value: 10 }, right: { label: "После", value: 20 },
        delta: 10, change_percent: 100, assessment: "observed",
        interpretation: "Разница не доказывает причинность." } }],
  } }]} />);

  expect(screen.getByText("Сравнение продаж")).toBeInTheDocument();
  expect(screen.getByText("До")).toBeInTheDocument();
  expect(screen.getByText("После")).toBeInTheDocument();
  expect(screen.getByText("+10")).toBeInTheDocument();
  expect(screen.getByText("Разница не доказывает причинность.")).toBeInTheDocument();
  expect(screen.queryByText("Технические данные · compare_groups")).not.toBeInTheDocument();
});

it("shows uncertainty and adjusted lag evidence without a causality claim", () => {
  render(<ToolResults results={[
    { tool_name: "compare_groups", ok: true, data: { statement: "Средний чек", results: [{
      id: "a", method: "compare", status: "completed", data: {
        left: { label: "До", value: 10 }, right: { label: "После", value: 15 }, delta: 5,
        uncertainty: { status: "estimated", method: "welch", left_count: 4, right_count: 4,
          p_value: 0.002, confidence_interval: { level: 0.95, low: 3, high: 7 } },
      },
    }] } },
    { tool_name: "analyze_relationship", ok: true, data: { statement: "Связь по месяцам", results: [{
      id: "b", method: "relationship", status: "completed", data: {
        correlation: 0.5, sample_size: 6, p_value: 0.03,
        lag_results: [{ lag: 0, correlation: 0.5, adjusted_p_value: 0.09, sample_size: 6 },
          { lag: 1, correlation: 0.8, adjusted_p_value: 0.01, sample_size: 5 }],
      },
    }] } },
  ]} />);

  expect(screen.getByText(/Доверительный интервал разницы/)).toBeInTheDocument();
  expect(screen.getByText(/Лаг 1/)).toBeInTheDocument();
  expect(screen.getByText(/p с поправкой/)).toBeInTheDocument();
});
