import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  type Profile,
  type Row,
  type Source,
  type SourceSchema,
} from "../../api";
import { DataTable, ErrorNotice, Icon, ToolResults } from "../../components";
import type { Entry, View } from "../chat/types";

import { EviaMascot } from "../../components/EviaMascot";

type SourceData = {
  id: string;
  schema: SourceSchema;
  rows: Row[];
  profile: Profile;
};
const formatNumber = (number: number) => number.toLocaleString("ru-RU");
const typeNames: Record<string, string> = {
  string: "Текст",
  integer: "Целое число",
  number: "Число",
  boolean: "Да / нет",
  unknown: "Не определён",
};

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
  const rowCounts =
    current?.schema.objects.map((object) => object.row_count) ?? [];
  const totalRows =
    rowCounts.length && rowCounts.every((count) => count !== null)
      ? rowCounts.reduce<number>((sum, count) => sum + (count ?? 0), 0)
      : null;
  const fields =
    current?.schema.objects.flatMap((object) => object.fields) ?? [];
  const views: [View, string][] = [
    ["preview", "Данные"],
    ["schema", "Схема"],
    ["profile", "Профиль"],
    ["results", "Результат"],
  ];
  return (
    <>
      <div className="analysis-heading">
        <div>
          <h1>{source.name}</h1>
          <p className="source-line">
            <span className="status-dot" />
            CSV · {source.status === "available" ? "Доступен" : source.status}
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
      <div className="metrics" aria-label="Сведения об источнике">
        <div>
          <span>Строк в источнике</span>
          <strong>{totalRows === null ? "—" : formatNumber(totalRows)}</strong>
        </div>
        <div>
          <span>Столбцов</span>
          <strong>{current ? formatNumber(fields.length) : "—"}</strong>
        </div>
        <div>
          <span>Строк в выборке</span>
          <strong>
            {current ? formatNumber(current.profile.sample_size) : "—"}
          </strong>
          <small>Для профиля данных</small>
        </div>
      </div>
      <section className="data-card" aria-label="Исследование данных">
        <div className="tabs" aria-label="Разделы источника">
          {views.map(([id, label]) => (
            <button
              key={id}
              aria-pressed={view === id}
              onClick={() => setView(id)}
            >
              {label}
              {id === "results" && entry?.answer && (
                <span className="tab-count">
                  {entry.answer.tool_results.length}
                </span>
              )}
            </button>
          ))}
        </div>
        {view === "results" ? (
          <div className="results-pane">
            <div className="pane-heading">
              <div>
                <h2>Результаты инструментов</h2>
              </div>
            </div>
            {entry?.answer ? (
              <>
                <p className="result-question">{entry.question}</p>
                <ToolResults results={entry.answer.tool_results} />
              </>
            ) : (
              <div className="empty-table">
                <Icon name="chat" size={30} />
                <p>
                  {entry?.state === "pending"
                    ? "Эвия работает над вопросом"
                    : "Здесь появится результат"}
                </p>
                <span>
                  {entry?.state === "error"
                    ? "Повторите вопрос в диалоге."
                    : "Задайте вопрос об источнике в диалоге справа."}
                </span>
              </div>
            )}
          </div>
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
        ) : view === "preview" ? (
          <>
            <div className="pane-heading">
              <div>
                <h2>Предпросмотр данных</h2>
                <p>
                  Первые {formatNumber(current.rows.length)} строк · максимум
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
        ) : view === "schema" ? (
          <div className="pane-padding">
            <div className="pane-heading compact">
              <div>
                <h2>Структура источника</h2>
                <p>Типы определены автоматически по выборке.</p>
              </div>
            </div>
            {current.schema.objects.length === 0 ? (
              <p className="muted">В источнике нет объектов схемы.</p>
            ) : (
              current.schema.objects.map((object) => (
                <section key={object.object_id}>
                  <h3 className="object-name">{object.name}</h3>
                  <div className="schema-list">
                    {object.fields.map((field, i) => (
                      <div className="schema-field" key={`${field.name}-${i}`}>
                        <span className="field-type">
                          {field.inferred_type === "string"
                            ? "Aa"
                            : field.inferred_type === "boolean"
                              ? "✓"
                              : "#"}
                        </span>
                        <div>
                          <strong>{field.name}</strong>
                          <small>
                            {typeNames[field.inferred_type] ||
                              field.inferred_type}
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
        ) : (
          <div className="pane-padding">
            <div className="pane-heading compact">
              <div>
                <h2>Профиль выборки</h2>
                <p>
                  По {formatNumber(current.profile.sample_size)} строкам из
                  первых {formatNumber(current.profile.sample_limit)}.
                </p>
              </div>
              <span className="pill">Выборка</span>
            </div>
            <p className="sample-note">
              Частоты, пропуски и уникальные значения относятся только к
              выборке, а не ко всему источнику.
            </p>
            {Object.entries(current.profile.columns).map(([name, column]) => (
              <section className="profile-column" key={name}>
                <h3>{name}</h3>
                <dl>
                  <div>
                    <dt>Заполнено</dt>
                    <dd>{formatNumber(column.sample_non_null_count)}</dd>
                  </div>
                  <div>
                    <dt>Пропуски</dt>
                    <dd>{formatNumber(column.sample_null_count)}</dd>
                  </div>
                  <div>
                    <dt>Уникальных</dt>
                    <dd>{formatNumber(column.distinct_sample_values)}</dd>
                  </div>
                </dl>
                <small>Частые значения в выборке</small>
                <div className="top-values">
                  {column.top_values.length ? (
                    column.top_values.map((item, i) => (
                      <span key={i}>
                        {item.value}
                        <b>{formatNumber(item.count)}</b>
                      </span>
                    ))
                  ) : (
                    <span>Нет заполненных значений</span>
                  )}
                </div>
              </section>
            ))}
            <details className="profile-note">
              <summary>Примечание сервера</summary>
              <p>{current.profile.note}</p>
            </details>
          </div>
        )}
      </section>
    </>
  );
}
