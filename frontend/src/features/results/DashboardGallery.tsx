import { useEffect, useState } from "react";
import { useLanguage } from "../../language";
import { api, errorMessage, type SavedDashboardInfo } from "../../api";
import { ErrorNotice } from "../../components";
import { SavedDashboard } from "./SavedDashboard";
import "./dashboardGallery.css";

type GalleryItem = SavedDashboardInfo["dashboard"] & { origin_chat_id?: string | null };

function chartsText(count: number) {
  const remainder = count % 100;
  const digit = remainder % 10;
  return `${count} ${remainder > 10 && remainder < 20 ? "графиков" : digit === 1 ? "график" : digit > 1 && digit < 5 ? "графика" : "графиков"}`;
}

export function DashboardGallery({ onClose, onAttach, onOpenOrigin }: { onClose: () => void; onAttach?: (id: string, title: string) => void; onOpenOrigin?: (chatId: string) => boolean }) {
  const { t } = useLanguage();
  const [revision, setRevision] = useState(0);
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("dashboard"));
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

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
              result.status === "fulfilled" && result.value.success ? [{ ...result.value.dashboard, origin_chat_id: result.value.origin_chat_id }] : [])]);
          }
          offset += ids.length;
          if (ids.length < 100) break;
        }
        if (failedDetails && !controller.signal.aborted)
          setError(t(`Не удалось загрузить ${failedDetails} из сохранённых отчётов. Повторите загрузку списка.`, `Could not load ${failedDetails} saved reports. Retry loading the list.`));
      } catch (cause) {
        if (!controller.signal.aborted) setError(errorMessage(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [revision]);

  const selected = items.find((item) => item.id === selectedId);
  function select(id: string) {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("dashboard", id);
    window.history.pushState({}, "", url);
  }

  async function removeSelected() {
    if (!deleteId) return;
    setDeleting(true);
    try {
      await api.deleteDashboard(deleteId);
      setItems((previous) => previous.filter((item) => item.id !== deleteId));
      if (selectedId === deleteId) {
        setSelectedId(null);
        const url = new URL(window.location.href);
        url.searchParams.delete("dashboard");
        window.history.replaceState({}, "", url);
      }
      setDeleteId(null);
      setError("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setDeleting(false);
    }
  }
  return <section className="dashboard-gallery" aria-label={t("Сохранённые отчёты", "Saved reports")}>
    <header className="dashboard-gallery-heading">
      <div><span>{t("Рабочее пространство", "Workspace")}</span><h1>{t("Сохранённые отчёты", "Saved reports")}</h1><p>{t("Графики и показатели, которые EVIA сохранила после анализа.", "Charts and metrics saved by EVIA after analysis.")}</p></div>
      <div className="dashboard-gallery-actions"><button type="button" onClick={onClose}>{t("К источнику", "Back to source")}</button><button type="button" onClick={() => setRevision((value) => value + 1)}>{t("Обновить список", "Refresh list")}</button></div>
    </header>
    {error && <ErrorNotice message={error} onRetry={() => setRevision((value) => value + 1)} label={t("Повторить загрузку отчётов", "Retry loading reports")} />}
    {loading && <p className="dashboard-gallery-status" role="status">{t("Загружаем отчёты…", "Loading reports…")}</p>}
    {!loading && !error && !items.length && <div className="dashboard-gallery-empty"><h2>{t("Пока нет сохранённых отчётов", "No saved reports yet")}</h2><p>{t("Попросите EVIA построить дашборд по выбранному источнику — готовый отчёт появится здесь.", "Ask EVIA to build a dashboard for a source; the saved report will appear here.")}</p></div>}
    {items.length > 0 && <div className="dashboard-gallery-list" aria-label={t("Список отчётов", "Report list")}>
      {items.map((item) => <button key={item.id} type="button" className={selectedId === item.id ? "selected" : ""} aria-pressed={selectedId === item.id} onClick={() => select(item.id)}>
        <span className="dashboard-gallery-tile" aria-hidden="true">▥</span><span><strong>{item.title}</strong><small>{t(chartsText(item.charts.length), `${item.charts.length} charts`)}{item.summary ? ` · ${item.summary}` : ""}</small></span><span aria-hidden="true">→</span>
      </button>)}
    </div>}
    {selected && <div className="dashboard-gallery-open">
      <div className="dashboard-gallery-open-actions">
        {onAttach && <button type="button" className="dashboard-gallery-attach" onClick={() => onAttach(selected.id, selected.title)}>{t("Обсудить этот отчёт в чате →", "Discuss this report in chat →")}</button>}
        {selected.origin_chat_id && onOpenOrigin && <button type="button" onClick={() => {
          if (!onOpenOrigin(selected.origin_chat_id!)) setError(t("Исходный диалог больше не доступен.", "The original chat is no longer available."));
        }}>{t("Открыть исходный диалог", "Open original chat")}</button>}
        <button type="button" onClick={() => setDeleteId(selected.id)}>{t("Удалить отчёт", "Delete report")}</button>
      </div>
      <SavedDashboard id={selected.id} editable />
    </div>}
    {deleteId && <div className="dashboard-gallery-confirm-backdrop"><div role="dialog" aria-modal="true" aria-label={t("Удалить отчёт", "Delete report")} className="dashboard-gallery-confirm">
      <h2>{t("Удалить отчёт?", "Delete report?")}</h2><p>{t("Отчёт исчезнет из списка. Это действие нельзя отменить.", "The report will be removed. This cannot be undone.")}</p>
      <div><button type="button" disabled={deleting} onClick={() => setDeleteId(null)}>{t("Отмена", "Cancel")}</button>
        <button type="button" disabled={deleting} onClick={() => void removeSelected()}>{deleting ? t("Удаляем…", "Deleting…") : t("Удалить", "Delete")}</button></div>
    </div></div>}
  </section>;
}
