import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { GeneratedDashboard } from "./GeneratedDashboard";

it("shows persisted period filters and quarterly grouping in the calculation passport", () => {
  render(<GeneratedDashboard scope="test" dashboard={{ version: 1, title: "Отчёт", cards: [{
    id: "q", type: "line", title: "Кварталы", status: "success",
    definition: {
      type: "line", x: { field: "Дата", source_id: "s", type: "temporal", time_grain: "quarter" },
      y: { field: "Сумма", source_id: "s", aggregate: "sum" },
      filters: [
        { field: { source_id: "s", field: "Дата" }, operator: "gte", value: "2025-01-01" },
        { field: { source_id: "s", field: "Дата" }, operator: "lt", value: "2026-01-01" },
      ],
    },
    data: { points: [{ x: "2025-01-01", y: 60 }] },
  }] }} />);
  expect(screen.getByText("По кварталам: Дата")).toBeInTheDocument();
  expect(screen.getByText("Дата ≥ 2025-01-01; Дата < 2026-01-01")).toBeInTheDocument();
  expect(screen.queryByText("Весь источник без фильтров")).not.toBeInTheDocument();
});
