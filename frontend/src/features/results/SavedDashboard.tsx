import { useEffect, useState } from "react";
import { api, ApiError, errorMessage, type SavedDashboardBuild } from "../../api";
import { ErrorNotice } from "../../components";
import { GeneratedDashboard, type Dashboard } from "./GeneratedDashboard";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function savedDashboardId(data: unknown): string | null {
  if (!record(data) || data.success !== true || !record(data.dashboard)) return null;
  return typeof data.dashboard.id === "string" && data.dashboard.id ? data.dashboard.id : null;
}

export function dashboardFromBuild(build: SavedDashboardBuild): Dashboard {
  return {
    version: 1,
    title: build.dashboard.title,
    cards: [...build.charts].sort((left, right) => left.position - right.position).map((chart): Dashboard["cards"][number] => {
      const definition = record(chart.definition) ? chart.definition : null;
      const type = definition?.type;
      if (!definition || (type !== "kpi" && type !== "line")) return {
        id: chart.chart_id,
        type: "kpi" as const,
        title: "Недоступный график",
        status: "error" as const,
        error: chart.error,
      };
      return {
        id: chart.chart_id,
        type,
        title: typeof definition.title === "string" ? definition.title : "График",
        status: chart.success ? "success" as const : "error" as const,
        definition: chart.definition,
        data: chart.result,
        error: chart.error,
      };
    }),
  };
}

export function SavedDashboard({ id }: { id: string }) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ id: string; build?: SavedDashboardBuild; error?: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    void api.dashboardBuild(id, controller.signal).then((build) => {
      if (!controller.signal.aborted) setState({ id, build });
    }).catch((error) => {
      if (!controller.signal.aborted) setState({ id, error: error instanceof ApiError && error.status === 404
        ? "Сохранённый дашборд больше не доступен."
        : errorMessage(error) });
    });
    return () => controller.abort();
  }, [id, revision]);

  const current = state?.id === id ? state : null;
  if (!current) return <div className="loading-panel" role="status">Открываем сохранённый дашборд…</div>;
  if (current.error) return <ErrorNotice message={current.error} onRetry={() => setRevision((value) => value + 1)} label="Повторить загрузку дашборда" />;
  const dashboard = dashboardFromBuild(current.build!);
  return <section className="saved-dashboard" aria-label="Сохранённый дашборд">
    <div className="saved-dashboard-toolbar"><span>Сохранённый дашборд</span><button type="button" onClick={() => setRevision((value) => value + 1)}>Обновить данные</button></div>
    {dashboard.cards.length ? <GeneratedDashboard dashboard={dashboard} scope={`saved-${id}`} sourceLabel={current.build!.success ? "Карточки пересчитаны по текущим данным" : "Часть карточек не удалось пересчитать"} />
      : <p className="dashboard-empty">В этом дашборде пока нет графиков.</p>}
  </section>;
}
