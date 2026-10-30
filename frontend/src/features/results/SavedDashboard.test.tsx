import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

it("keeps the previous result visible when refresh fails", async () => {
  const load = vi.spyOn(api, "dashboardBuild")
    .mockResolvedValueOnce(build)
    .mockRejectedValueOnce(new Error("Сервис недоступен"));
  render(<SavedDashboard id="report-1" />);
  expect(await screen.findByText("Выручка")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Обновить данные" }));
  await waitFor(() => expect(screen.getByText(/Показаны предыдущие данные/)).toBeInTheDocument());
  expect(screen.getByText("30")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(2);
  vi.restoreAllMocks();
});

it("persists changed chart order and renders it immediately", async () => {
  vi.spyOn(api, "dashboardBuild").mockResolvedValue(build);
  const save = vi.spyOn(api, "dashboardOrder").mockResolvedValue({ success: true,
    dashboard: { ...build.dashboard, version: 2, charts: [
      { chart_id: "trend", position: 0 }, { chart_id: "total", position: 1 },
    ] },
  });
  render(<SavedDashboard id="report-1" editable />);
  expect((await screen.findAllByText("Выручка")).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "Опустить Выручка" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("report-1", ["trend", "total"], 1));
  await waitFor(() => expect(screen.getByRole("button", { name: "Поднять Выручка" })).not.toBeDisabled());
  vi.restoreAllMocks();
});

it("shows a stale saved result and refreshes it explicitly", async () => {
  const old = { ...build, stale: true };
  vi.spyOn(api, "dashboardBuild").mockResolvedValue(old);
  const refresh = vi.spyOn(api, "refreshDashboard").mockResolvedValue({ ...build, stale: false });
  render(<SavedDashboard id="report-1" />);
  expect(await screen.findByText(/Источник изменился/)).toBeInTheDocument();
  expect(screen.getByText("30")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Обновить данные" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledWith("report-1", expect.any(AbortSignal)));
  await waitFor(() => expect(screen.queryByText(/Источник изменился/)).not.toBeInTheDocument());
  vi.restoreAllMocks();
});
