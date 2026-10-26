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
