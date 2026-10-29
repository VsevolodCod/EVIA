import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import { api } from "../../api";
import { DashboardGallery } from "./DashboardGallery";

it("lists stored reports by title and reopens one from the server", async () => {
  vi.spyOn(api, "dashboardIds").mockResolvedValue({ dashboard_ids: ["report-1"] });
  vi.spyOn(api, "dashboardInfo").mockResolvedValue({ success: true, origin_chat_id: "chat-1", dashboard: {
    id: "report-1", title: "Продажи", version: 1, charts: [{ chart_id: "total", position: 0 }],
  } });
  const build = vi.spyOn(api, "dashboardBuild").mockResolvedValue({ success: true,
    dashboard: { id: "report-1", title: "Продажи", version: 1, charts: [{ chart_id: "total", position: 0 }] },
    charts: [{ chart_id: "total", position: 0, success: true, chart_type: "kpi",
      definition: { type: "kpi", title: "Выручка" }, result: { value: 30 } }],
  });
  const onAttach = vi.fn();
  const onOpenOrigin = vi.fn().mockReturnValue(true);
  render(<DashboardGallery onClose={() => {}} onAttach={onAttach} onOpenOrigin={onOpenOrigin} />);
  fireEvent.click(await screen.findByRole("button", { name: /Продажи/ }));
  expect(await screen.findByText("Выручка")).toBeInTheDocument();
  expect(build).toHaveBeenCalledWith("report-1", expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("button", { name: /Обсудить этот отчёт/ }));
  expect(onAttach).toHaveBeenCalledWith("report-1", "Продажи");
  fireEvent.click(screen.getByRole("button", { name: "Открыть исходный диалог" }));
  expect(onOpenOrigin).toHaveBeenCalledWith("chat-1");
});

it("shows a retry when saved report details fail to load", async () => {
  vi.spyOn(api, "dashboardIds").mockResolvedValue({ dashboard_ids: ["report-1"] });
  vi.spyOn(api, "dashboardInfo").mockRejectedValue(new Error("Сервис временно недоступен"));
  render(<DashboardGallery onClose={() => {}} />);
  expect(await screen.findByText(/Не удалось загрузить 1 из сохранённых отчётов/)).toBeInTheDocument();
  expect(screen.queryByText("Пока нет сохранённых отчётов")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить загрузку отчётов" })).toBeInTheDocument();
});

it("opens a deep link after reload and requires confirmation before deletion", async () => {
  window.history.replaceState({}, "", "/?dashboard=report-1");
  vi.spyOn(api, "dashboardIds").mockResolvedValue({ dashboard_ids: ["report-1"] });
  vi.spyOn(api, "dashboardInfo").mockResolvedValue({ success: true, dashboard: {
    id: "report-1", title: "Продажи", version: 1, charts: [],
  } });
  vi.spyOn(api, "dashboardBuild").mockResolvedValue({ success: true,
    dashboard: { id: "report-1", title: "Продажи", version: 1, charts: [] }, charts: [],
  });
  const remove = vi.spyOn(api, "deleteDashboard").mockResolvedValue({ success: true });
  render(<DashboardGallery onClose={() => {}} />);
  expect(await screen.findByRole("button", { name: "Удалить отчёт" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Удалить отчёт" }));
  expect(remove).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "Удалить отчёт" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Удалить отчёт" }));
  fireEvent.click(screen.getByRole("button", { name: /^Удалить$/ }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith("report-1"));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Удалить отчёт" })).not.toBeInTheDocument());
  expect(new URLSearchParams(window.location.search).has("dashboard")).toBe(false);
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});
