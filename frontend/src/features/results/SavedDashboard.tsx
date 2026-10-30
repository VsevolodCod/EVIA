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
      if (!definition || !["kpi", "line", "bar", "scatter", "table"].includes(String(type))) return {
        id: chart.chart_id,
        type: "kpi" as const,
        title: "Недоступный график",
        status: "error" as const,
        error: chart.error,
      };
      return {
        id: chart.chart_id,
        type: type as Dashboard["cards"][number]["type"],
        title: typeof definition.title === "string" ? definition.title : "График",
        status: chart.success ? "success" as const : "error" as const,
        definition: chart.definition,
        data: chart.result,
        error: chart.error,
      };
    }),
  };
}

export function SavedDashboard({ id, editable = false }: { id: string; editable?: boolean }) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ id: string; build?: SavedDashboardBuild; error?: string; refreshing?: boolean; updatedAt?: number } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => previous?.id === id && previous.build
      ? { ...previous, refreshing: true, error: undefined } : null);
    const load = revision === 0 ? api.dashboardBuild(id, controller.signal) : api.refreshDashboard(id, controller.signal);
    void load.then((build) => {
      if (!controller.signal.aborted) setState({ id, build, updatedAt: Date.now() });
    }).catch((error) => {
      if (!controller.signal.aborted) setState((previous) => ({
        id, build: previous?.id === id ? previous.build : undefined,
        updatedAt: previous?.id === id ? previous.updatedAt : undefined,
        error: error instanceof ApiError && error.status === 404
          ? "Сохранённый дашборд больше не доступен."
          : `Не удалось обновить отчёт. ${errorMessage(error)}`,
      }));
    });
    return () => controller.abort();
  }, [id, revision]);

  const current = state?.id === id ? state : null;
  if (!current) return <div className="loading-panel" role="status">Открываем сохранённый дашборд…</div>;
  if (current.error && !current.build) return <ErrorNotice message={current.error} onRetry={() => setRevision((value) => value + 1)} label="Повторить загрузку дашборда" />;
  if (!current.build) return <div className="loading-panel" role="status">Открываем сохранённый дашборд…</div>;
  const dashboard = dashboardFromBuild(current.build!);
  const ordered = [...current.build.dashboard.charts].sort((left, right) => left.position - right.position);
  async function move(index: number, direction: -1 | 1) {
    const next = ordered.map((item) => item.chart_id);
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    setSaving(true);
    try {
      const saved = await api.dashboardOrder(id, next, current!.build!.dashboard.version);
      setState((previous) => previous?.id === id && previous.build ? {
        ...previous, error: undefined,
        build: {
          ...previous.build, dashboard: saved.dashboard,
          charts: previous.build.charts.map((chart) => ({ ...chart, position: next.indexOf(chart.chart_id) })),
        },
      } : previous);
    } catch (error) {
      setState((previous) => previous?.id === id ? { ...previous, error: errorMessage(error) } : previous);
    } finally {
      setSaving(false);
    }
  }
  return <section className="saved-dashboard" aria-label="Сохранённый дашборд">
    <div className="saved-dashboard-toolbar"><span>Сохранённый дашборд{current.updatedAt ? ` · обновлён ${new Date(current.updatedAt).toLocaleString("ru-RU")}` : ""}</span><button type="button" disabled={current.refreshing} onClick={() => setRevision((value) => value + 1)}>{current.refreshing ? "Обновляем…" : "Обновить данные"}</button></div>
    {current.error && <ErrorNotice message={current.build ? `${current.error} Показаны предыдущие данные.` : current.error} onRetry={() => setRevision((value) => value + 1)} label="Повторить загрузку дашборда" />}
    {current.build.stale && <p role="status">Источник изменился. Показан сохранённый результат; нажмите «Обновить данные» для пересчёта.</p>}
    {current.refreshing && <p role="status">Обновляем графики…</p>}
    {!current.build.success && <p role="status">Часть графиков не обновилась. Остальные результаты доступны ниже.</p>}
    {editable && ordered.length > 1 && <div className="saved-dashboard-order" aria-label="Порядок графиков">
      {ordered.map((ref, index) => {
        const chart = current.build!.charts.find((item) => item.chart_id === ref.chart_id);
        const rawDefinition = chart?.definition;
        const definition = record(rawDefinition) ? rawDefinition : null;
        const title = typeof definition?.title === "string" ? definition.title : `График ${index + 1}`;
        return <div key={ref.chart_id}><span>{title}</span>
          <button type="button" disabled={saving || index === 0} aria-label={`Поднять ${title}`} onClick={() => void move(index, -1)}>↑</button>
          <button type="button" disabled={saving || index === ordered.length - 1} aria-label={`Опустить ${title}`} onClick={() => void move(index, 1)}>↓</button>
        </div>;
      })}
    </div>}
    {dashboard.cards.length ? <GeneratedDashboard dashboard={dashboard} scope={`saved-${id}`} sourceLabel={current.build!.success ? "Сохранённый результат" : "Часть карточек недоступна"} />
      : <p className="dashboard-empty">В этом дашборде пока нет графиков.</p>}
  </section>;
}
