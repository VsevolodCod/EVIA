import { useEffect, useState } from "react";
import { api, errorMessage, type SavedDashboardInfo } from "../../api";
import { ErrorNotice } from "../../components";
import { SavedDashboard } from "./SavedDashboard";
import "./dashboardGallery.css";

type GalleryItem = SavedDashboardInfo["dashboard"];

function chartsText(count: number) {
  const remainder = count % 100;
  const digit = remainder % 10;
  return `${count} ${remainder > 10 && remainder < 20 ? "графиков" : digit === 1 ? "график" : digit > 1 && digit < 5 ? "графика" : "графиков"}`;
}

export function DashboardGallery({ onClose, onAttach }: { onClose: () => void; onAttach?: (id: string, title: string) => void }) {
  const [revision, setRevision] = useState(0);
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    setLoading(true);
    setError("");
    void (async () => {
      try {
        let offset = 0;
        let failedDetails = 0;
        while (!controller.signal.aborted) {
          const { dashboard_ids: ids } = await api.dashboardIds(controller.signal, offset);
          for (let start = 0; start < ids.length && !controller.signal.aborted; start += 6) {
            const batch = await Promise.allSettled(ids.slice(start, start + 6).map((id) => api.dashboardInfo(id, controller.signal)));
            if (controller.signal.aborted) return;
            failedDetails += batch.filter((result) => result.status === "rejected" || !result.value.success).length;
            setItems((previous) => [...previous, ...batch.flatMap((result) =>
              result.status === "fulfilled" && result.value.success ? [result.value.dashboard] : [])]);
          }
          offset += ids.length;
          if (ids.length < 100) break;
        }
        if (failedDetails && !controller.signal.aborted)
          setError(`Не удалось загрузить ${failedDetails} из сохранённых отчётов. Повторите загрузку списка.`);
      } catch (cause) {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [revision]);

  const selected = items.find((item) => item.id === selectedId);
  return <section className="dashboard-gallery" aria-label="Сохранённые отчёты">
    <header className="dashboard-gallery-heading">
      <div><span>Рабочее пространство</span><h1>Сохранённые отчёты</h1><p>Графики и показатели, которые EVIA сохранила после анализа.</p></div>
      <div className="dashboard-gallery-actions"><button type="button" onClick={onClose}>К источнику</button><button type="button" onClick={() => setRevision((value) => value + 1)}>Обновить список</button></div>
    </header>
    {error && <ErrorNotice message={error} onRetry={() => setRevision((value) => value + 1)} label="Повторить загрузку отчётов" />}
    {loading && <p className="dashboard-gallery-status" role="status">Загружаем отчёты…</p>}
    {!loading && !error && !items.length && <div className="dashboard-gallery-empty"><h2>Пока нет сохранённых отчётов</h2><p>Попросите EVIA построить дашборд по выбранному источнику — готовый отчёт появится здесь.</p></div>}
    {items.length > 0 && <div className="dashboard-gallery-list" aria-label="Список отчётов">
      {items.map((item) => <button key={item.id} type="button" className={selectedId === item.id ? "selected" : ""} aria-pressed={selectedId === item.id} onClick={() => setSelectedId(item.id)}>
        <span className="dashboard-gallery-tile" aria-hidden="true">▥</span><span><strong>{item.title}</strong><small>{chartsText(item.charts.length)}{item.summary ? ` · ${item.summary}` : ""}</small></span><span aria-hidden="true">→</span>
      </button>)}
    </div>}
    {selected && <div className="dashboard-gallery-open">
      {onAttach && <button type="button" className="dashboard-gallery-attach" onClick={() => onAttach(selected.id, selected.title)}>Обсудить этот отчёт в чате →</button>}
      <SavedDashboard id={selected.id} />
    </div>}
  </section>;
}
