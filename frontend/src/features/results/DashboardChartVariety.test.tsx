import { render, screen } from "@testing-library/react";
import type { SavedDashboardBuild } from "../../api";
import { GeneratedDashboard, generatedChartFrom, generatedDashboardFrom } from "./GeneratedDashboard";
import { dashboardFromBuild } from "./SavedDashboard";

const cards = [
  { id: "bar", type: "bar" as const, title: "По категориям", status: "success" as const,
    definition: { type: "bar", title: "По категориям", x: { source_id: "sales", field: "category" }, y: { source_id: "sales", field: "amount", aggregate: "sum" } },
    data: { x: { field: "category" }, y: { field: "amount" }, points: [{ x: "A", y: 30 }, { x: "B", y: -5 }], limit_reached: true, limit: 2 } },
  { id: "scatter", type: "scatter" as const, title: "Связь показателей", status: "success" as const,
    definition: { type: "scatter", title: "Связь показателей", x: { source_id: "sales", field: "revenue" }, y: { source_id: "sales", field: "cost" } },
    data: { x: { field: "revenue" }, y: { field: "cost" }, points: [{ x: 10, y: 5 }, { x: 10, y: 5 }], limit_reached: false, limit: 100 } },
  { id: "table", type: "table" as const, title: "Строки", status: "success" as const,
    definition: { type: "table", title: "Строки", fields: [{ source_id: "sales", field: "category" }, { source_id: "sales", field: "note" }] },
    data: { columns: ["category", "note"], rows: [{ category: "A", note: "ok" }, { category: "B", note: null }], limit_reached: false, limit: 100 } },
];

it("renders bounded bars, duplicate scatter points and an accessible table from computed data", () => {
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards }} scope="variety-test" />);
  expect(screen.getByRole("img", { name: /По категориям/ }).querySelectorAll("rect[data-bar]")).toHaveLength(2);
  expect(screen.getByRole("img", { name: /Связь показателей/ }).querySelectorAll("circle[data-point]")).toHaveLength(2);
  expect(screen.getByRole("region", { name: "Строки" })).toBeInTheDocument();
  expect(screen.getByText("ok")).toBeInTheDocument();
  expect(screen.getByText(/Достигнут лимит выдачи/)).toBeInTheDocument();
});

it("accepts generated and saved chart payloads without dropping new types", () => {
  for (const card of cards) {
    expect(generatedDashboardFrom({ tool_name: "create_dashboard", ok: true,
      data: { version: 1, title: "Панель", cards: [card] } })?.cards[0].type).toBe(card.type);
    expect(generatedChartFrom({ tool_name: "build_chart", ok: true,
      data: { success: true, chart_id: card.id, definition: card.definition, result: card.data } })?.cards[0].type).toBe(card.type);
  }
  const build: SavedDashboardBuild = {
    success: true,
    dashboard: { id: "dashboard", title: "Панель", version: 1,
      charts: cards.map((card, position) => ({ chart_id: card.id, position })) },
    charts: cards.map((card, position) => ({ chart_id: card.id, position, success: true,
      chart_type: card.type, definition: card.definition, result: card.data })),
  };
  expect(dashboardFromBuild(build).cards.map(card => card.type)).toEqual(["bar", "scatter", "table"]);
});
