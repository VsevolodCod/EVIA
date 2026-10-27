import { fireEvent, render, screen } from "@testing-library/react";
import { api, type SavedDashboardBuild } from "../../api";
import { SavedDashboard, dashboardFromBuild, savedDashboardId } from "./SavedDashboard";

const build: SavedDashboardBuild = {
  success: true,
  dashboard: { id: "report-1", title: "Продажи", version: 1, charts: [
    { chart_id: "trend", position: 1 }, { chart_id: "total", position: 0 },
  ] },
  charts: [
    { chart_id: "trend", position: 1, success: true, chart_type: "line",
      definition: { type: "line", title: "По месяцам" },
      result: { x: { field: "month" }, y: { field: "revenue" }, points: [{ x: "Январь", y: 10 }, { x: "Февраль", y: 20 }] } },
    { chart_id: "total", position: 0, success: true, chart_type: "kpi",
      definition: { type: "kpi", title: "Выручка" }, result: { value: 30 } },
  ],
};

it("renders saved charts in their stored order and refreshes on request", async () => {
  const load = vi.spyOn(api, "dashboardBuild").mockResolvedValue(build);
  const dashboard = dashboardFromBuild(build);
  expect(dashboard.cards.map((card) => card.title)).toEqual(["Выручка", "По месяцам"]);
  render(<SavedDashboard id="report-1" />);
  expect(await screen.findByText("Выручка")).toBeInTheDocument();
  expect(screen.getByText("30")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Обновить данные" }));
  expect(await screen.findByText("Выручка")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(2);
  vi.restoreAllMocks();
});

it("accepts only a successfully saved dashboard id", () => {
  expect(savedDashboardId({ success: true, dashboard: { id: "report-1" } })).toBe("report-1");
  expect(savedDashboardId({ success: false, dashboard: { id: "report-1" } })).toBeNull();
  expect(savedDashboardId({ success: true, dashboard: { id: "" } })).toBeNull();
});

it("keeps a failed saved chart visible instead of calling the dashboard empty", () => {
  const failed = dashboardFromBuild({
    success: false,
    dashboard: { id: "report-2", title: "Продажи", version: 1, charts: [{ chart_id: "lost", position: 0 }] },
    charts: [{ chart_id: "lost", position: 0, success: false, error: { code: "chart_not_found", message: "Saved chart not found" } }],
  });
  expect(failed.cards).toMatchObject([{ id: "lost", status: "error", title: "Недоступный график" }]);
});
