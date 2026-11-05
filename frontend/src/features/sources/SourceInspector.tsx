import { useEffect, useState } from "react";
import { useLanguage } from "../../language";
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
const views: [View, string, string][] = [
  ["overview", "Обзор", "Overview"],
  ["profile", "Столбцы", "Columns"],
  ["quality", "Качество", "Quality"],
  ["preview", "Данные", "Data"],
  ["schema", "Схема", "Schema"],
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
  const { t, language } = useLanguage();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  async function deleteCsv() {
    if (!onDelete || deleting || deleteDisabled) return;
    if (!window.confirm(t(`Удалить «${source.name}» и все версии CSV? Действие нельзя отменить. Сохранённые отчёты по этому источнику нельзя будет обновить.`, `Delete “${source.name}” and all CSV versions? This cannot be undone. Saved reports using this source will no longer be refreshable.`))) return;
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
        {source.source_type === "csv" && onDelete && <button className="source-delete" type="button" disabled={deleting || deleteDisabled} onClick={() => void deleteCsv()}>{deleting ? t("Удаляем…", "Deleting…") : t("Удалить CSV", "Delete CSV")}</button>}
        <button className="source-refresh" type="button" onClick={() => setRevision((value) => value + 1)}>
          <Icon name="refresh" size={16} /> {t("Обновить", "Refresh")}
        </button>
      </div>
      {deleteError && <p role="alert" className="source-delete-error">{t("Не удалось удалить CSV", "Could not delete CSV")}: {deleteError}</p>}
      <nav className="analytics-tabs" aria-label={t("Разделы источника", "Source sections")}>
        {views.map(([id, ru, en]) => { const label = t(ru, en); return (
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
        ); })}
        {view === "results" && <button aria-pressed="true" onClick={() => setView("results")}>{t("Результат анализа", "Analysis result")}</button>}
      </nav>
      <section className="analytics-report" aria-label="Исследование данных">
        {view === "results" ? (
          <AnalysisResult entry={entry} onOpenChat={onOpenChat} />
        ) : error ? (
          <div className="pane-padding">
            <ErrorNotice
              message={error}
              onRetry={() => setRevision((value) => value + 1)}
              label={t("Повторить загрузку", "Retry loading")}
            />
          </div>
        ) : !current ? (
          <div className="loading-panel" role="status">
            <EviaMascot state="profiling" size={80} decorative />
            {t("Изучаем структуру источника…", "Inspecting source structure…")}
          </div>
        ) : (
          <>
            {view === "overview" ? (
              <Dashboard
                title={t("Обзор источника", "Source overview")}
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
                    message={t(`Не удалось построить профиль: ${profileError}`, `Could not build profile: ${profileError}`)}
                    onRetry={() => setRevision((value) => value + 1)}
                    label={t("Повторить расчёт", "Retry calculation")}
                  />
                </div>
              ) : (
                <div className="loading-panel" role="status">
                  <EviaMascot state="profiling" size={80} decorative />
                  {t("Рассчитываем профиль источника…", "Calculating source profile…")}
                </div>
              )
            ) : view === "quality" ? (
              model ? <ProfileQuality model={model} onColumn={openColumn} /> : profileError ? (
                <div className="pane-padding">
                  <ErrorNotice
                    message={t(`Не удалось построить профиль: ${profileError}`, `Could not build profile: ${profileError}`)}
                    onRetry={() => setRevision((value) => value + 1)}
                    label={t("Повторить расчёт", "Retry calculation")}
                  />
                </div>
              ) : (
                <div className="loading-panel" role="status">
                  <EviaMascot state="profiling" size={80} decorative />
                  {t("Рассчитываем профиль источника…", "Calculating source profile…")}
                </div>
              )
            ) : view === "preview" ? (
              <>
                <div className="pane-heading">
                  <div>
                    <h2>{t("Предпросмотр данных", "Data preview")}</h2>
                  </div>
                </div>
                <DataTable
                  rows={current.rows}
                  columns={current.schema.objects[0]?.fields.map(
                    (field) => field.name,
                  )}
                  label={t("Предпросмотр источника", "Source preview")}
                />
              </>
            ) : (
              <div className="analytics-section">
                <div className="analytics-title">
                  <div>
                    <h2>{t("Структура источника", "Source structure")}</h2>
                  </div>
                </div>
                {source.import_report && <details className="csv-import-details">
                  <summary>{t("Отчёт об импорте", "Import report")}</summary>
                  <p>{t(`Принято ${numberText(source.import_report.accepted_rows)} из ${numberText(source.import_report.rows_read)} строк · отклонено ${numberText(source.import_report.rejected_rows)}`, `Accepted ${numberText(source.import_report.accepted_rows)} of ${numberText(source.import_report.rows_read)} rows · rejected ${numberText(source.import_report.rejected_rows)}`)}</p>
                  <p>{t("Кодировка", "Encoding")}: {source.import_report.encoding.toUpperCase()} · {t("разделитель", "delimiter")}: {source.import_report.delimiter === "\t" ? t("табуляция", "tab") : source.import_report.delimiter}</p>
                  {source.import_report.warnings.length > 0 && <ul>{source.import_report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
                  {source.csv_versions?.map((version, index) => <a
                    key={version.snapshot_id}
                    href={`/sources/${encodeURIComponent(source.source_id)}/versions/${encodeURIComponent(version.snapshot_id)}/download`}
                  >{t("Скачать оригинал", "Download original")} {index + 1}</a>)}
                  {onReimport && <label className="csv-reimport">
                    {t("Повторно импортировать CSV", "Reimport CSV")}
                    <input type="file" accept=".csv,text/csv" aria-label={t("Повторно импортировать CSV", "Reimport CSV")} onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) onReimport(file, source.source_id);
                      event.target.value = "";
                    }} />
                  </label>}
                </details>}
                {!current.schema.objects.length ? (
                  <p className="muted">{t("В источнике нет объектов схемы.", "The source contains no schema objects.")}</p>
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
                                {typeLabel(field.inferred_type, language)}
                                {field.is_identifier_candidate
                                  ? t(" · Возможный идентификатор", " · Possible identifier")
                                  : ""}
                              </small>
                              {field.description && <p>{field.description}</p>}
                            </div>
                            <span className="nullable">
                              {field.nullable === null
                                ? t("Нет выборки", "No sample")
                                : field.nullable
                                  ? t("Есть пропуски", "Missing values")
                                  : t("Без пропусков", "No missing values")}
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
                <summary>{t("Как рассчитан профиль", "How the profile is calculated")}</summary>
                <p>
                  {t(`Источник: ${source.name}. Версия схемы: ${current.schema.version}. Число строк датасета берётся из схемы;`, `Source: ${source.name}. Schema version: ${current.schema.version}. Dataset row count comes from the schema;`)}{" "}{current.profile.coverage === "full"
                    ? t("заполненность, NULL, пустые строки и уникальность рассчитаны по всему датасету. Частые значения — из профиля выборки.", "completeness, NULLs, empty strings and uniqueness cover the full dataset. Frequent values come from the sample profile.")
                    : t("остальные показатели — из профиля выборки. Заполненность — доля непустых ячеек среди ячеек с доступной статистикой. Частые значения сравниваются как исходные строки.", "other metrics come from the sample profile. Completeness is the share of non-empty cells among cells with available statistics. Frequent values are compared as original strings.")}
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
