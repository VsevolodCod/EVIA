import { useMemo, useState } from "react";
import type { Profile, Row, Source, SourceSchema, ToolResult } from "../../api";
import type { Entry } from "../chat/types";
import { SafeMarkdown } from "../chat/SafeMarkdown";
import { hasExactStats, numberText, typeLabel } from "../sources/profileModel";
import { PieChart } from "../results/ResultVisualization";
import { generatedChartFrom, generatedDashboardFrom, GeneratedDashboard } from "../results/GeneratedDashboard";
import { pieChartData } from "../results/resultChartModel";
import "./reportBuilder.css";

type Props = {
  source: Source;
  schema: SourceSchema;
  rows: Row[];
  profile?: Profile;
  entries: Entry[];
  onClose: () => void;
};

const calculationTools = new Set(["query_data", "execute_sql", "run_sql"]);

function readable(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return numberText(value);
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function tableFrom(result: ToolResult): { columns: string[]; rows: unknown[][]; truncated: boolean } | null {
  if (!result.ok || !calculationTools.has(result.tool_name)) return null;
  const data = result.data;
  if (Array.isArray(data) && data.every((row) => row && typeof row === "object" && !Array.isArray(row))) {
    const columns = [...new Set(data.flatMap((row) => Object.keys(row as Record<string, unknown>)))];
    return columns.length ? { columns, rows: data.map((row) => columns.map((name) => (row as Record<string, unknown>)[name])), truncated: false } : null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const query = data as { columns?: unknown; rows?: unknown; truncated?: unknown };
  if (!Array.isArray(query.columns) || !Array.isArray(query.rows)) return null;
  const columns = query.columns.map((column) => column && typeof column === "object" && "name" in column ? column.name : null);
  if (!columns.length || columns.some((name) => typeof name !== "string") ||
    !query.rows.every((row) => Array.isArray(row) && row.length === columns.length)) return null;
  return { columns: columns as string[], rows: query.rows as unknown[][], truncated: query.truncated === true };
}

function generatedTable(data: unknown): { columns: string[]; rows: unknown[][]; truncated: boolean } | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const table = data as { columns?: unknown; rows?: unknown; limit_reached?: unknown };
  if (!Array.isArray(table.columns) || !Array.isArray(table.rows) ||
    !table.columns.every((name) => typeof name === "string") ||
    !table.rows.every((row) => row && typeof row === "object" && !Array.isArray(row))) return null;
  const columns = table.columns as string[];
  return { columns, rows: table.rows.map((row) => columns.map((name) => (row as Record<string, unknown>)[name])),
    truncated: table.limit_reached === true };
}

function ReportTable({ columns, rows, caption }: { columns: string[]; rows: unknown[][]; caption: string }) {
  const groups = Array.from({ length: Math.ceil(columns.length / 8) }, (_, index) =>
    columns.slice(index * 8, (index + 1) * 8));
  return <div className="report-table-wrap">
    {groups.map((group, groupIndex) => <table key={groupIndex}>
      <caption>{caption}{groups.length > 1 ? ` · поля ${groupIndex * 8 + 1}–${groupIndex * 8 + group.length} из ${columns.length}` : ""}</caption>
      <thead><tr>{group.map((name, index) => <th key={`${name}-${index}`}>{name}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index}>{group.map((_, column) =>
        <td key={column}>{readable(row[groupIndex * 8 + column])}</td>)}</tr>)}</tbody>
    </table>)}
  </div>;
}

function sourceCount(schema: SourceSchema): number | null {
  return schema.objects.length && schema.objects.every((object) => object.row_count !== null)
    ? schema.objects.reduce((total, object) => total + (object.row_count ?? 0), 0)
    : null;
}

function sourcePie(schema: SourceSchema, rows: Row[]) {
  const field = schema.objects.flatMap((object) => object.fields)
    .find((column) => column.inferred_type === "string" && !column.is_identifier_candidate);
  if (!field) return null;
  const counts = new Map<string, number>();
  for (const row of rows) {
    const value = row[field.name];
    if (value === null || value === undefined || value === "") continue;
    const label = String(value);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  if (counts.size < 2) return null;
  const slices = pieChartData([...counts].map(([label, value]) => ({ label, value })));
  return slices ? { field: field.name, slices } : null;
}

function shortConclusion(answer: string) {
  const plain = answer.replace(/[`*_#>\[\]]/g, " ").replace(/\s+/g, " ").trim();
  if (plain.length <= 180) return plain;
  return `${plain.slice(0, 177).trimEnd()}…`;
}

function counted(noun: [string, string, string], value: number) {
  const lastTwo = value % 100;
  const last = value % 10;
  return `${numberText(value)} ${lastTwo >= 11 && lastTwo <= 14 ? noun[2] :
    last === 1 ? noun[0] : last >= 2 && last <= 4 ? noun[1] : noun[2]}`;
}

export function ReportBuilder({ source, schema, rows, profile, entries, onClose }: Props) {
  const available = entries.filter((entry) => entry.state === "success" && entry.answer &&
    entry.answer.status !== "error" && entry.answer.status !== "clarification" &&
    entry.answer.answer_kind !== "demo");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const selected = available.filter((entry) => selectedIds.includes(entry.id));
  const fields = schema.objects.flatMap((object) => object.fields);
  const previewColumns = fields.length ? fields.map((field) => field.name) : Object.keys(rows[0] ?? {});
  const rowCount = sourceCount(schema);
  const pie = useMemo(() => sourcePie(schema, rows), [schema, rows]);
  const affectedFields = profile ? Object.values(profile.columns).filter((column) => {
    const exact = profile.coverage === "full" && hasExactStats(column);
    return (exact ? column.null_count + column.empty_count : column.sample_null_count) > 0;
  }).length : null;
  const problems = profile ? Object.entries(profile.columns).flatMap(([name, column]) => {
    const exact = profile.coverage === "full" && hasExactStats(column);
    const missing = exact ? column.null_count : column.sample_null_count;
    const empty = exact ? column.empty_count : 0;
    return [
      ...(missing ? [`${name}: ${counted(["пропуск", "пропуска", "пропусков"], missing)}`] : []),
      ...(empty ? [`${name}: ${counted(["пустое значение", "пустых значения", "пустых значений"], empty)}`] : []),
    ];
  }) : [];
  const reportDate = new Date().toLocaleDateString("ru-RU");

  function printReport() {
    const previousTitle = document.title;
    document.title = `EVIA — отчёт — ${source.name}`;
    window.addEventListener("afterprint", () => { document.title = previousTitle; }, { once: true });
    window.print();
  }

  return <div className="report-builder" role="dialog" aria-modal="true" aria-label="Составить PDF-отчёт">
    <div className="report-builder-panel">
      <header className="report-builder-head"><h2>PDF-отчёт</h2>
        <button type="button" aria-label="Закрыть отчёт" onClick={onClose}>✕</button></header>
      <div className="report-builder-controls">
        {available.length > 0 && <div className="report-builder-selection"><h3>Добавить ответы EVIA</h3>
          <div className="report-builder-selection-actions">
            <button type="button" onClick={() => setSelectedIds(available.map((entry) => entry.id))}>Выбрать все</button>
            <button type="button" onClick={() => setSelectedIds([])}>Снять выбор</button>
          </div>{available.map((entry) => <label key={entry.id} className="report-builder-choice">
            <input type="checkbox" checked={selectedIds.includes(entry.id)} onChange={(event) =>
              setSelectedIds((ids) => event.target.checked ? [...ids, entry.id] : ids.filter((id) => id !== entry.id))} />
            <span>{entry.question}</span></label>)}
        </div>}
        <button type="button" className="report-builder-print" onClick={printReport}>Сохранить в PDF</button>
      </div>
    </div>
    <article className="report-document" aria-label="PDF-отчёт">
      <header className="report-document-header"><div className="report-document-brand"><strong>EVIA</strong><span>Отчёт по данным</span></div>
        <h1>{source.name}</h1><p>{source.source_type === "csv" ? "CSV" : "PostgreSQL"} · {reportDate}</p></header>
      <section className="report-section"><h2>Краткая сводка</h2>
        <div className="report-facts">
          <div><span>Строк</span><strong className="report-fact-value">{rowCount === null ? "—" : numberText(rowCount)}</strong></div>
          <div><span>Столбцов</span><strong className="report-fact-value">{numberText(fields.length)}</strong></div>
          <div><span>Поля с пропусками</span><strong className="report-fact-value">{affectedFields === null ? "—" : numberText(affectedFields)}</strong></div>
        </div>
        {selected.length > 0 && <div className="report-key-findings"><h3>Ключевые выводы</h3><ul>
          {selected.map((entry) => <li key={entry.id}><strong>{entry.question}</strong> — {shortConclusion(entry.answer?.answer ?? "")}</li>)}
        </ul></div>}
      </section>
      <section className="report-section"><h2>Состав данных</h2>
        {fields.length ? <table><thead><tr><th>Поле</th><th>Тип</th><th>Пропуски</th></tr></thead><tbody>
          {fields.map((field) => <tr key={field.name}><td>{field.name}</td><td>{typeLabel(field.inferred_type)}</td>
            <td>{profile?.columns[field.name] ? numberText(profile.coverage === "full" && hasExactStats(profile.columns[field.name])
              ? profile.columns[field.name].null_count : profile.columns[field.name].sample_null_count) : "—"}</td></tr>)}
        </tbody></table> : <p>Схема источника пуста.</p>}
      </section>
      <section className="report-section"><h2>Первые строки</h2>
        {rows.length ? <ReportTable columns={previewColumns}
          rows={rows.slice(0, 5).map((row) => previewColumns.map((name) => row[name]))}
          caption={`Первые ${Math.min(rows.length, 5)} из ${rowCount === null ? "доступных" : numberText(rowCount)} строк`} /> : <p>Строк для просмотра нет.</p>}
      </section>
      <section className="report-section"><h2>Качество данных</h2>
        {profile ? <>{profile.coverage === "sample" && <p className="report-scope-note">По выборке из {numberText(profile.sample_size)} строк.</p>}
          {problems.length ? <ul className="report-quality-issues">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
            : <p>Пропусков и пустых значений не найдено{profile.coverage === "sample" ? " в выборке" : ""}.</p>}</>
          : <p>Данные о пропусках пока недоступны.</p>}
        {source.import_report && (source.import_report.rejected_rows > 0 || source.import_report.warnings.length > 0) && <div className="report-import"><h3>Импорт CSV</h3>
          {source.import_report.rejected_rows > 0 && <p>Отклонено строк при импорте: {numberText(source.import_report.rejected_rows)}.</p>}
          {source.import_report.warnings.length > 0 && <ul>{source.import_report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
        </div>}
      </section>
      {pie && <section className="report-section"><h2>Распределение: {pie.field}</h2>
        <PieChart slices={pie.slices} label={`Круговая диаграмма по полю ${pie.field}`} />
        <p className="report-note">По первым {numberText(rows.length)} строкам, без пустых значений.</p></section>}
      {selected.length > 0 && <section className="report-section report-ai"><h2>Расчёты и выводы EVIA</h2>
        {selected.map((entry, index) => <div className="report-calculation" key={entry.id}>
          <h3>{index + 1}. {entry.question}</h3>
          <SafeMarkdown>{entry.answer?.answer ?? ""}</SafeMarkdown>
          {entry.answer?.analysis?.sql && <div className="report-sql"><strong>SQL расчёта</strong><pre>{entry.answer.analysis.sql}</pre></div>}
          {entry.answer?.tool_results.map((result, resultIndex) => {
            const table = tableFrom(result);
            const chart = generatedDashboardFrom(result) ?? generatedChartFrom(result);
            return <div key={resultIndex}>
              {table && <><ReportTable columns={table.columns} rows={table.rows} caption={`Результат расчёта ${resultIndex + 1}`} />
                {table.truncated && <p className="report-note">Сервер вернул усечённый результат; полный объём не входит в отчёт.</p>}</>}
              {chart && <>{chart.cards.some((card) => card.type !== "table") &&
                <GeneratedDashboard dashboard={{ ...chart, cards: chart.cards.filter((card) => card.type !== "table") }}
                  scope={`report-${entry.id}-${resultIndex}`} expandPassports />}
                {chart.cards.filter((card) => card.type === "table").map((card) => {
                  const savedTable = generatedTable(card.data);
                  return savedTable && <div key={card.id}><ReportTable columns={savedTable.columns} rows={savedTable.rows}
                    caption={card.title} />{savedTable.truncated &&
                    <p className="report-note">Таблица ограничена сервером; в отчёте все возвращённые строки.</p>}</div>;
                })}</>}
            </div>;
          })}
        </div>)}
      </section>}
      <footer className="report-document-footer">EVIA · {source.name} · {reportDate}</footer>
    </article>
  </div>;
}
