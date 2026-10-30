import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultVisualization } from "./ResultVisualization";
import { ToolResults } from "./ToolResults";

it("shows a separate pie chart with grouped categories and percentages", () => {
  render(<ResultVisualization rows={[{ category: "A", amount: 2 }, { category: "A", amount: 1 },
    { category: "B", amount: 3 }]} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Круговая" }));
  const chart = screen.getByRole("img", { name: /Круговая диаграмма: amount по category/ });
  expect(chart).toBeInTheDocument();
  expect(screen.getByText(/A.*50%/)).toBeInTheDocument();
  expect(screen.getByText(/B.*50%/)).toBeInTheDocument();
});

it("does not offer a pie chart for negative or zero-only values", () => {
  const { rerender } = render(<ResultVisualization rows={[{ category: "A", amount: -1 },
    { category: "B", amount: 2 }]} label="Результат" />);
  expect(screen.queryByRole("button", { name: "Круговая" })).not.toBeInTheDocument();
  rerender(<ResultVisualization rows={[{ category: "A", amount: 0 }, { category: "B", amount: 0 }]} label="Результат" />);
  expect(screen.queryByRole("button", { name: "Круговая" })).not.toBeInTheDocument();
});

it("keeps all thirteen categories when switching between table, bars and line", () => {
  const rows = Array.from({ length: 13 }, (_, i) => ({ category: `Категория ${i + 1}`, amount: i + 1 }));
  render(<ResultVisualization rows={rows} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  const bars = screen.getByRole("img", { name: "Столбчатый график: amount по category" });
  expect(bars.querySelectorAll("rect")).toHaveLength(13);
  expect(bars.querySelector('rect[aria-label="Категория 13: 13"]')).not.toBeNull();
  expect(screen.getByText(/Точки 1–13 из 13/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  expect(screen.getByRole("img").querySelectorAll("circle")).toHaveLength(13);
  fireEvent.click(screen.getByRole("button", { name: "Таблица" }));
  expect(within(screen.getByRole("region", { name: "Результат" })).getByText("Категория 13")).toBeInTheDocument();
});

it.each([
  [-10, 20], [-20, -10], [0, 0], [5, 5], [.0002, .0004], [-1e308, 1e308],
])("draws finite non-negative bar geometry for values %j and %j", (first, second) => {
  render(<ResultVisualization rows={[{ category: "A", amount: first }, { category: "B", amount: second }]} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  const svg = screen.getByRole("img");
  const baseline = Number(svg.querySelector(".result-zero-line")?.getAttribute("y1"));
  [...svg.querySelectorAll("rect")].forEach((bar, index) => {
    const y = Number(bar.getAttribute("y"));
    const height = Number(bar.getAttribute("height"));
    expect(Number.isFinite(y)).toBe(true);
    expect(Number.isFinite(height)).toBe(true);
    expect(height).toBeGreaterThanOrEqual(0);
    expect(y).toBeGreaterThanOrEqual(20 - 1e-8);
    expect(y + height).toBeLessThanOrEqual(187 + 1e-8);
    if ([first, second][index] < 0) expect(y).toBeCloseTo(baseline);
    else expect(y + height).toBeCloseTo(baseline);
  });
});

it("offers every page of a large chart without losing the last category", () => {
  const rows = Array.from({ length: 101 }, (_, i) => ({ category: `row-${i + 1}`, amount: i + 1 }));
  render(<ResultVisualization rows={rows} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getByRole("img").querySelectorAll("rect")).toHaveLength(50);
  expect(screen.getByRole("button", { name: "Предыдущие точки" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Следующие точки" }));
  expect(screen.getByText(/Точки 51–100 из 101/)).toBeInTheDocument();
  expect(screen.getByRole("img").querySelectorAll("rect")).toHaveLength(50);
  fireEvent.click(screen.getByRole("button", { name: "Следующие точки" }));
  expect(screen.getByRole("img").querySelector('rect[aria-label="row-101: 101"]')).not.toBeNull();
  expect(screen.getByText(/Точки 101–101 из 101/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Следующие точки" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Предыдущие точки" }));
  expect(screen.getByText(/Точки 51–100 из 101/)).toBeInTheDocument();
});

it("uses padded IDs as labels and preserves them after switching back to the table", () => {
  render(<ResultVisualization rows={[{ id: "001", amount: 10 }, { id: "002", amount: 20 }]} label="Результат" />);
  expect(within(screen.getByLabelText("Показатель")).queryByRole("option", { name: "id" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  const svg = screen.getByRole("img", { name: "Столбчатый график: amount по id" });
  expect(svg.querySelector('rect[aria-label="001: 10"]')).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Таблица" }));
  expect(screen.getByText("001", { selector: "td" })).toBeInTheDocument();
});

it("resets the chart page when a new result has the same column names", () => {
  const rows = Array.from({ length: 101 }, (_, i) => ({ category: `old-${i}`, amount: i }));
  const { rerender } = render(<ResultVisualization rows={rows} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  fireEvent.click(screen.getByRole("button", { name: "Следующие точки" }));
  rerender(<ResultVisualization rows={rows.map(row => ({ ...row, category: row.category.replace("old", "new") }))} label="Результат" />);
  expect(screen.getByText(/Точки 1–50 из 101/)).toBeInTheDocument();
  expect(screen.getByRole("img").querySelector('rect[aria-label="new-0: 0"]')).not.toBeNull();
});

it("allows keyboard navigation to select fields and activate a chart", async () => {
  const user = userEvent.setup();
  render(<ResultVisualization rows={[{ category: "A", amount: 10 }]} label="Результат" />);
  await user.tab();
  expect(screen.getByLabelText("Показатель")).toHaveFocus();
  await user.tab();
  expect(screen.getByLabelText("Подписи")).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Таблица" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Столбцы" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("img", { name: "Столбчатый график: amount по category" })).toBeInTheDocument();
});

it("honors numeric and string QueryResult types instead of guessing from cells", () => {
  render(<ToolResults results={[{ tool_name: "query_data", ok: true, data: {
    columns: [{ name: "segment", data_type: "string" }, { name: "amount", data_type: "decimal" }],
    rows: [["123", "1,25"], ["456", "2.50"]],
  } }]} />);
  expect(within(screen.getByLabelText("Показатель")).queryByRole("option", { name: "segment" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getByRole("img", { name: "Столбчатый график: amount по segment" }).querySelectorAll("rect")).toHaveLength(2);
});

it("requires a measure choice when several numeric fields are available", () => {
  render(<ResultVisualization rows={[{ category: "A", revenue: 10, profit: 2 }]} label="Результат" />);
  expect(screen.queryByRole("button", { name: "Столбцы" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Показатель"), { target: { value: "profit" } });
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  expect(screen.getByRole("img", { name: "Столбчатый график: profit по category" }).querySelector('rect[aria-label="A: 2"]')).not.toBeNull();
  fireEvent.change(screen.getByLabelText("Показатель"), { target: { value: "revenue" } });
  expect(screen.getByRole("img", { name: "Столбчатый график: revenue по category" }).querySelector('rect[aria-label="A: 10"]')).not.toBeNull();
});

it("keeps null gaps and repeated labels instead of joining or aggregating them", () => {
  render(<ResultVisualization rows={[{ month: "A", amount: 10 }, { month: "B", amount: null }, { month: "A", amount: 20 }]} label="Результат" />);
  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  const svg = screen.getByRole("img");
  expect(svg.querySelectorAll("polyline")).toHaveLength(2);
  expect(svg.querySelectorAll("circle")).toHaveLength(2);
  expect(svg.querySelector('circle[aria-label="A: 10"]')).not.toBeNull();
  expect(svg.querySelector('circle[aria-label="A: 20"]')).not.toBeNull();
  expect(screen.getByText(/Пропущено значений: 1/)).toBeInTheDocument();
});

it("falls back to the new table when the source no longer has the chosen measure", () => {
  const { rerender } = render(<ResultVisualization rows={[{ category: "A", revenue: 10, profit: 2 }]} label="Результат" />);
  fireEvent.change(screen.getByLabelText("Показатель"), { target: { value: "profit" } });
  fireEvent.click(screen.getByRole("button", { name: "Столбцы" }));
  rerender(<ResultVisualization rows={[{ city: "Томск", temperature: 5, pressure: 750 }]} label="Другой источник" />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Другой источник" })).toBeInTheDocument();
  expect(screen.queryByText("profit")).not.toBeInTheDocument();
});
