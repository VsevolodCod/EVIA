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
import { ProfileOverview } from "./ProfileOverview";
import { ProfileColumns } from "./ProfileColumns";
import { ProfileQuality } from "./ProfileQuality";
import {
  numberText,
  profileModel,
  sampleDescription,
  typeLabel,
} from "./profileModel";
import "./analytics.css";

type SourceData = {
  id: string;
  schema: SourceSchema;
  rows: Row[];
  profile: Profile;
};
const views: [View, string][] = [
  ["overview", "Обзор"],
  ["profile", "Столбцы"],
  ["quality", "Качество"],
  ["preview", "Данные"],
  ["schema", "Схема"],
  ["results", "Результат"],
];

export function SourceInspector({
  source,
  entry,
  view,
  setView,
}: {
  source: Source;
  entry?: Entry;
  view: View;
  setView: (view: View) => void;
}) {
  const [data, setData] = useState<SourceData | null>(null);
  const [failure, setFailure] = useState<{
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
    Promise.all([
      api.schema(source.source_id, controller.signal),
      api.preview(source.source_id, controller.signal),
      api.profile(source.source_id, controller.signal),
    ])
      .then(([schema, rows, profile]) => {
        if (!controller.signal.aborted)
          setData({ id: source.source_id, schema, rows, profile });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setFailure({ id: source.source_id, message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [source.source_id, revision]);
  const current = data?.id === source.source_id ? data : null;
  const error = failure?.id === source.source_id ? failure.message : null;
  const model = current ? profileModel(current.schema, current.profile) : null;
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
      <div className="analysis-heading">
        <div>
          <p className="analytics-kicker">ИССЛЕДОВАНИЕ ДАННЫХ</p>
          <h1>{source.name}</h1>
          <p className="source-line">
            <span className="status-dot" />
            {source.source_type.toUpperCase()} ·{" "}
            {source.status === "available" ? "Доступен" : source.status}
          </p>
        </div>
        <button
          className="icon-button"
          aria-label="Обновить данные источника"
          onClick={() => setRevision((value) => value + 1)}
        >
          <Icon name="refresh" />
        </button>
      </div>
      <div className="analytics-metrics" aria-label="Сведения об источнике">
        <div>
          <span>Строк в источнике</span>
          <strong>
            {model?.totalRows == null ? "—" : numberText(model.totalRows)}
          </strong>
          <small>Полный датасет</small>
        </div>
        <div>
          <span>Столбцов</span>
          <strong>{model ? numberText(model.fields.length) : "—"}</strong>
          <small>В схеме источника</small>
        </div>
        <div>
          <span>Строк изучено</span>
          <strong>
            {current ? numberText(current.profile.sample_size) : "—"}
          </strong>
          <small>Для профиля выборки</small>
        </div>
      </div>
      <section className="analytics-report" aria-label="Исследование данных">
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
        </nav>
        {view === "results" ? (
          <AnalysisResult entry={entry} />
        ) : error ? (
          <div className="pane-padding">
            <ErrorNotice
              message={error}
              onRetry={() => setRevision((value) => value + 1)}
              label="Повторить загрузку"
            />
          </div>
        ) : !current || !model ? (
          <div className="loading-panel" role="status">
            <EviaMascot state="profiling" size={80} decorative />
            Изучаем структуру источника…
          </div>
        ) : (
          <>
            {["overview", "profile", "quality"].includes(view) && (
              <div className="profile-scope">
                <span className="scope-dot" aria-hidden="true" />
                <p>
                  {sampleDescription(current.profile)}
                  <small>
                    Статистика относится к выборке, а не ко всему источнику.
                  </small>
                </p>
              </div>
            )}
            {view === "overview" ? (
              <ProfileOverview
                model={model}
                profile={current.profile}
                onColumn={openColumn}
                onQuality={() => setView("quality")}
                onColumns={() => openColumn("")}
              />
            ) : view === "profile" ? (
              <ProfileColumns
                key={`${source.source_id}-${columnSelection.revision}`}
                fields={model.fields}
                initialSearch={
                  columnSelection.sourceId === source.source_id
                    ? columnSelection.name
                    : ""
                }
              />
            ) : view === "quality" ? (
              <ProfileQuality model={model} onColumn={openColumn} />
            ) : view === "preview" ? (
              <>
                <div className="pane-heading">
                  <div>
                    <h2>Предпросмотр данных</h2>
                    <p>
                      Первые {numberText(current.rows.length)} строк · максимум
                      100
                    </p>
                  </div>
                  <Icon name="grid" />
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
                    <span className="analytics-kicker">
                      УСТРОЙСТВО ДАТАСЕТА
                    </span>
                    <h2>Структура источника</h2>
                  </div>
                </div>
                <p className="analytics-caption">
                  Типы определены автоматически по выборке.
                </p>
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
            {["overview", "profile", "quality"].includes(view) && (
              <details className="profile-method">
                <summary>Как рассчитан профиль</summary>
                <p>
                  Источник: {source.name}. Версия схемы:{" "}
                  {current.schema.version}. Число строк датасета берётся из
                  схемы; остальные показатели — из профиля выборки.
                  Заполненность — доля непустых ячеек среди ячеек с доступной
                  статистикой. Частые значения сравниваются как исходные строки.
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
