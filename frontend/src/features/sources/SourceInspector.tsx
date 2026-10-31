import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type Profile,
  type Row,
  type Source,
  type SourceSchema,
} from "../../api";
import { DataTable, ErrorNotice, Icon } from "../../components";
import type { Entry, View } from "../chat/types";
import { EviaMascot } from "../../components/EviaMascot";
import { AnalysisResult } from "../results/AnalysisResult";
import { Dashboard } from "../analytics/Dashboard";
import { ProfileColumns } from "./ProfileColumns";
import { ProfileQuality } from "./ProfileQuality";
import {
  numberText,
  profileModel,
  typeLabel,
} from "./profileModel";
import "./analytics.css";

type SourceData = {
  id: string;
  schema: SourceSchema;
  rows: Row[];
  profile?: Profile;
};
const views: [View, string][] = [
  ["overview", "Обзор"],
  ["profile", "Столбцы"],
  ["quality", "Качество"],
  ["preview", "Данные"],
  ["schema", "Схема"],
];

function sourceRowCount(schema: SourceSchema) {
  return schema.objects.reduce<number | null>((total, object) =>
    total === null || object.row_count === null ? null : total + object.row_count,
  0);
}

export function SourceInspector({
  source,
  entry,
  reportEntries = [],
  view,
  setView,
  onOpenChat,
  onReimport,
  onDelete,
  deleteDisabled = false,
}: {
  source: Source;
  entry?: Entry;
  reportEntries?: Entry[];
  view: View;
  setView: (view: View) => void;
  onOpenChat?: () => void;
  onReimport?: (file: File, sourceId: string) => void;
  onDelete?: (sourceId: string) => Promise<void>;
  deleteDisabled?: boolean;
}) {
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  async function deleteCsv() {
    if (!onDelete || deleting || deleteDisabled) return;
    if (!window.confirm(`Удалить «${source.name}» и все версии CSV? Действие нельзя отменить. Сохранённые отчёты по этому источнику нельзя будет обновить.`)) return;
    setDeleteError("");
    setDeleting(true);
    try {
      await onDelete(source.source_id);
    } catch (error) {
      setDeleteError(errorMessage(error));
    } finally {
      setDeleting(false);
    }
  }
  const [data, setData] = useState<SourceData | null>(null);
  const [failure, setFailure] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [profileFailure, setProfileFailure] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [columnSelection, setColumnSelection] = useState({
    sourceId: source.source_id,
    name: "",
    revision: 0,
  });
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setFailure(null);
    setProfileFailure(null);
    let loadedProfile: Profile | undefined;
    void api.profile(source.source_id, controller.signal)
      .then((profile) => {
        if (profile.coverage === "full" && profile.snapshot_id !== source.snapshot_id) {
          if (!controller.signal.aborted) {
            setProfileFailure({
              id: source.source_id,
              message: "Профиль относится к другой версии источника. Обновите данные и повторите расчёт.",
            });
          }
          return;
        }
        loadedProfile = profile;
        if (!controller.signal.aborted) {
          setData((previous) => previous?.id === source.source_id
            ? { ...previous, profile }
            : previous);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setProfileFailure({ id: source.source_id, message: errorMessage(error) });
        }
      });
    Promise.all([
      api.schema(source.source_id, controller.signal),
      api.preview(source.source_id, controller.signal),
    ])
      .then(([schema, rows]) => {
        if (!controller.signal.aborted)
          setData({ id: source.source_id, schema, rows, profile: loadedProfile });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setFailure({ id: source.source_id, message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [source.source_id, source.snapshot_id, revision]);
  const current = data?.id === source.source_id ? data : null;
  const error = failure?.id === source.source_id ? failure.message : null;
  const profileError = profileFailure?.id === source.source_id ? profileFailure.message : null;
  const model = current?.profile ? profileModel(current.schema, current.profile) : null;
  function openColumn(name: string) {
    setColumnSelection((previous) => ({
      sourceId: source.source_id,
      name,
      revision: previous.revision + 1,
    }));
    setView("profile");
  }

  return (
    <div className="analytics-workspace">
      <div className="source-workspace-heading">
        <div className="source-workspace-identity">
          <h1>{source.name}</h1>
        </div>
        {source.source_type === "csv" && onDelete && <button className="source-delete" type="button" disabled={deleting || deleteDisabled} onClick={() => void deleteCsv()}>{deleting ? "Удаляем…" : "Удалить CSV"}</button>}
        <button className="source-refresh" type="button" onClick={() => setRevision((value) => value + 1)}>
          <Icon name="refresh" size={16} /> Обновить
        </button>
      </div>
      {deleteError && <p role="alert" className="source-delete-error">Не удалось удалить CSV: {deleteError}</p>}
      <nav className="analytics-tabs" aria-label="Разделы источника">
        {views.map(([id, label]) => (
          <button
            key={id}
            aria-label={label}
            aria-pressed={view === id}
            onClick={() => (id === "profile" ? openColumn("") : setView(id))}
          >
            {label}
            {id === "quality" && Boolean(model?.missingFields.length) && (
              <span className="count-badge">
                {model!.missingFields.length}
              </span>
            )}
          </button>
        ))}
        {view === "results" && <button aria-pressed="true" onClick={() => setView("results")}>Результат анализа</button>}
      </nav>
      <section className="analytics-report" aria-label="Исследование данных">
        {view === "results" ? (
          <AnalysisResult entry={entry} onOpenChat={onOpenChat} />
        ) : error ? (
          <div className="pane-padding">
            <ErrorNotice
              message={error}
              onRetry={() => setRevision((value) => value + 1)}
              label="Повторить загрузку"
            />
          </div>
        ) : !current ? (
          <div className="loading-panel" role="status">
            <EviaMascot state="profiling" size={80} decorative />
            Изучаем структуру источника…
          </div>
        ) : (
          <>
            {view === "overview" ? (
              <Dashboard
                title="Обзор источника"
                sourceLabel={source.name}
                scope={source.source_id}
                schema={current.schema}
                rows={current.rows}
                profile={current.profile}
                fullSourceRows={sourceRowCount(current.schema)}
                onOpenData={() => setView("preview")}
                source={source}
                reportEntries={reportEntries}
              />
            ) : view === "profile" ? (
              model ? <ProfileColumns
                key={`${source.source_id}-${columnSelection.revision}`}
                fields={model.fields}
                sampleSize={current.profile?.sample_size ?? 0}
                candidateGrainKeys={current.profile?.coverage === "full"
                  ? current.profile.candidate_grain_keys ?? []
                  : []}
                initialSearch={
                  columnSelection.sourceId === source.source_id
                    ? columnSelection.name
                    : ""
                }
              /> : profileError ? (
                <div className="pane-padding">
                  <ErrorNotice
                    message={`Не удалось построить профиль: ${profileError}`}
                    onRetry={() => setRevision((value) => value + 1)}
                    label="Повторить расчёт"
                  />
                </div>
              ) : (
                <div className="loading-panel" role="status">
                  <EviaMascot state="profiling" size={80} decorative />
                  Рассчитываем профиль источника…
                </div>
              )
            ) : view === "quality" ? (
              model ? <ProfileQuality model={model} onColumn={openColumn} /> : profileError ? (
                <div className="pane-padding">
                  <ErrorNotice
                    message={`Не удалось построить профиль: ${profileError}`}
                    onRetry={() => setRevision((value) => value + 1)}
                    label="Повторить расчёт"
                  />
                </div>
              ) : (
                <div className="loading-panel" role="status">
                  <EviaMascot state="profiling" size={80} decorative />
                  Рассчитываем профиль источника…
                </div>
              )
            ) : view === "preview" ? (
              <>
                <div className="pane-heading">
                  <div>
                    <h2>Предпросмотр данных</h2>
                  </div>
                </div>
                <DataTable
                  rows={current.rows}
                  columns={current.schema.objects[0]?.fields.map(
                    (field) => field.name,
                  )}
                  label="Предпросмотр источника"
                />
              </>
            ) : (
              <div className="analytics-section">
                <div className="analytics-title">
                  <div>
                    <h2>Структура источника</h2>
                  </div>
                </div>
                {source.import_report && <details className="csv-import-details">
                  <summary>Отчёт об импорте</summary>
                  <p>Принято {numberText(source.import_report.accepted_rows)} из {numberText(source.import_report.rows_read)} строк · отклонено {numberText(source.import_report.rejected_rows)}</p>
                  <p>Кодировка: {source.import_report.encoding.toUpperCase()} · разделитель: {source.import_report.delimiter === "\t" ? "табуляция" : source.import_report.delimiter}</p>
                  {source.import_report.warnings.length > 0 && <ul>{source.import_report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                  {source.csv_versions?.map((version, index) => <a
                    key={version.snapshot_id}
                    href={`/sources/${encodeURIComponent(source.source_id)}/versions/${encodeURIComponent(version.snapshot_id)}/download`}
                  >Скачать оригинал {index + 1}</a>)}
                  {onReimport && <label className="csv-reimport">
                    Повторно импортировать CSV
                    <input type="file" accept=".csv,text/csv" aria-label="Повторно импортировать CSV" onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) onReimport(file, source.source_id);
                      event.target.value = "";
                    }} />
                  </label>}
                </details>}
                {!current.schema.objects.length ? (
                  <p className="muted">В источнике нет объектов схемы.</p>
                ) : (
                  current.schema.objects.map((object) => (
                    <section key={object.object_id}>
                      <h3 className="object-name">{object.name}</h3>
                      <div className="schema-list">
                        {object.fields.map((field) => (
                          <div className="schema-field" key={field.name}>
                            <span className="field-type">
                              {field.inferred_type === "string" ? "Aa" : "#"}
                            </span>
                            <div>
                              <strong>{field.name}</strong>
                              <small>
                                {typeLabel(field.inferred_type)}
                                {field.is_identifier_candidate
                                  ? " · Возможный идентификатор"
                                  : ""}
                              </small>
                              {field.description && <p>{field.description}</p>}
                            </div>
                            <span className="nullable">
                              {field.nullable === null
                                ? "Нет выборки"
                                : field.nullable
                                  ? "Есть пропуски"
                                  : "Без пропусков"}
                            </span>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))
                )}
              </div>
            )}
            {current.profile && model && ["profile", "quality"].includes(view) && (
              <details className="profile-method">
                <summary>Как рассчитан профиль</summary>
                <p>
                  Источник: {source.name}. Версия схемы:{" "}
                  {current.schema.version}. Число строк датасета берётся из
                  схемы; {current.profile.coverage === "full"
                    ? "заполненность, NULL, пустые строки и уникальность рассчитаны по всему датасету. Частые значения — из профиля выборки."
                    : "остальные показатели — из профиля выборки. Заполненность — доля непустых ячеек среди ячеек с доступной статистикой. Частые значения сравниваются как исходные строки."}
                </p>
                <p>{current.profile.note}</p>
              </details>
            )}
          </>
        )}
      </section>
    </div>
  );
}
