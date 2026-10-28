import { fireEvent, render, screen } from "@testing-library/react";
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

it("labels separate bar series instead of making duplicate categories ambiguous", () => {
  const bar = { ...cards[0], definition: { ...cards[0].definition, series: { source_id: "sales", field: "region" } },
    data: { ...cards[0].data, points: [
    { x: "A", y: 10, series: "Восток" }, { x: "A", y: 20, series: null },
  ] } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [bar] }} scope="series-test" />);
  const chart = screen.getByRole("img", { name: /По категориям/ });
  expect(chart.querySelector('rect[aria-label="A · Восток: 10"]')).not.toBeNull();
  expect(chart.querySelector('rect[aria-label="A · Нет значения: 20"]')).not.toBeNull();
  expect(screen.getByText("Восток")).toBeInTheDocument();
  expect(screen.getByText("Нет значения")).toBeInTheDocument();
  const bars = chart.querySelectorAll("rect[data-bar]");
  expect(bars[0].getAttribute("fill")).not.toBe(bars[1].getAttribute("fill"));
});

it("switches an aggregated chart between bars and a line without changing its computed points or currency", () => {
  const bar = { ...cards[0],
    definition: { ...cards[0].definition, y: { ...cards[0].definition.y,
      format: { type: "currency", decimals: 2, currency: "RUB" } } },
    data: { ...cards[0].data, y: { field: "amount", format: { type: "currency", decimals: 2, currency: "RUB" } } },
  };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [bar] }} scope="view-switch-test" />);

  const bars = screen.getByRole("img", { name: /По категориям/ });
  expect(bars.querySelectorAll("rect[data-bar]")).toHaveLength(2);
  expect(bars.querySelector('rect[aria-label*="₽"]')).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  const line = screen.getByRole("img", { name: /По категориям/ });
  expect(line.querySelectorAll("rect[data-bar]")).toHaveLength(0);
  expect(line.querySelectorAll('circle[aria-label*="₽"]')).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Линия" })).toHaveAttribute("aria-pressed", "true");
});

it("shows declared units for KPI and both scatter axes", () => {
  const kpi = { id: "kpi", type: "kpi" as const, title: "Выручка", status: "success" as const,
    definition: { type: "kpi", field: { source_id: "sales", field: "revenue" }, aggregate: "sum",
      format: { type: "currency", currency: "RUB", decimals: 2 } },
    data: { value: 10, format: { type: "currency", currency: "RUB", decimals: 2 } } };
  const scatter = { ...cards[1], data: { ...cards[1].data,
    x: { field: "revenue", format: { type: "currency", currency: "RUB", decimals: 2 } },
    y: { field: "cost", format: { type: "percent", decimals: 0 } } } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [kpi, scatter] }} scope="units-test" />);
  expect(screen.getByRole("heading", { name: "Выручка" }).closest("section")?.querySelector(".generated-value")?.textContent)
    .toMatch(/10,00\s*₽/);
  const points = screen.getByRole("img", { name: /Связь показателей/ }).querySelectorAll("circle[data-point]");
  expect(points[0].getAttribute("aria-label")).toMatch(/₽; 500\s*%/);
});

it("does not round a large exact decimal KPI through JavaScript Number", () => {
  const kpi = { id: "exact", type: "kpi" as const, title: "Точная сумма", status: "success" as const,
    definition: { type: "kpi", field: { source_id: "sales", field: "amount" }, aggregate: "sum" },
    data: { value: "9007199254740993.25", format: { type: "number", decimals: 2 } } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [kpi] }} scope="exact-decimal-test" />);
  const value = screen.getByRole("heading", { name: "Точная сумма" }).closest("section")?.querySelector(".generated-value")?.textContent;
  expect(value?.replace(/\s/g, "")).toBe("9007199254740993,25");
});

it("formats fractional percentage ticks without rounding them to two raw decimals first", () => {
  const line = { id: "ratio", type: "line" as const, title: "Доля", status: "success" as const,
    definition: { type: "line", x: { source_id: "sales", field: "month" },
      y: { source_id: "sales", field: "ratio", aggregate: "avg" } },
    data: { x: { field: "month" }, y: { field: "ratio", format: { type: "percent", decimals: 1 } },
      points: [{ x: "Jan", y: 0 }, { x: "Feb", y: 0.01 }] } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [line] }} scope="percent-ticks-test" />);
  expect(screen.getByRole("img", { name: /Доля/ }).textContent).toMatch(/0,5\s*%/);
});

it("keeps an unnamed series identifiable after switching bars to a line", () => {
  const bar = { ...cards[0], definition: { ...cards[0].definition, series: { source_id: "sales", field: "region" } },
    data: { ...cards[0].data, points: [
      { x: "A", y: 10, series: "Восток" }, { x: "A", y: 20, series: null },
    ] } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [bar] }} scope="series-switch-test" />);
  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  expect(screen.getByText("Нет значения")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /По категориям/ }).querySelector('circle[aria-label*="Нет значения"]')).not.toBeNull();
});

it("does not merge NULL with a literal series named Нет значения", () => {
  const bar = { ...cards[0], definition: { ...cards[0].definition, series: { source_id: "sales", field: "region" } },
    data: { ...cards[0].data, points: [
      { x: "A", y: 10, series: null }, { x: "A", y: 20, series: "Нет значения" },
    ] } };
  render(<GeneratedDashboard dashboard={{ version: 1, title: "Панель", cards: [bar] }} scope="literal-null-series-test" />);
  const bars = screen.getByRole("img", { name: /По категориям/ }).querySelectorAll("rect[data-bar]");
  expect(bars[0].getAttribute("fill")).not.toBe(bars[1].getAttribute("fill"));
  fireEvent.click(screen.getByRole("button", { name: "Линия" }));
  expect(screen.getByRole("img", { name: /По категориям/ }).querySelectorAll("polyline[data-testid^='generated-series-']"))
    .toHaveLength(2);
});
