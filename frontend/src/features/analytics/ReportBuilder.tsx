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

function ReportTable({ columns, rows, caption }: { columns: string[]; rows: unknown[][]; caption: string }) {
  const shownColumns = columns.slice(0, 8);
  const shownRows = rows.slice(0, 15);
  return <div className="report-table-wrap">
    <table><caption>{caption}</caption><thead><tr>{shownColumns.map((name, index) => <th key={`${name}-${index}`}>{name}</th>)}</tr></thead>
      <tbody>{shownRows.map((row, index) => <tr key={index}>{shownColumns.map((_, column) =>
        <td key={column}>{readable(row[column])}</td>)}</tr>)}</tbody></table>
    {(columns.length > shownColumns.length || rows.length > shownRows.length) &&
      <p className="report-note">Показаны {shownRows.length} из {rows.length} строк и {shownColumns.length} из {columns.length} столбцов.</p>}
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

export function ReportBuilder({ source, schema, rows, profile, entries, onClose }: Props) {
  const available = entries.filter((entry) => entry.state === "success" && entry.answer &&
    entry.answer.status !== "error" && entry.answer.status !== "clarification" &&
    entry.answer.answer_kind !== "demo");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const selected = available.filter((entry) => selectedIds.includes(entry.id));
  const fields = schema.objects.flatMap((object) => object.fields);
  const rowCount = sourceCount(schema);
  const pie = useMemo(() => sourcePie(schema, rows), [schema, rows]);
  const problems = profile ? Object.entries(profile.columns).flatMap(([name, column]) => {
    const exact = profile.coverage === "full" && hasExactStats(column);
    const missing = exact ? column.null_count : column.sample_null_count;
    const empty = exact ? column.empty_count : 0;
    return [
      ...(missing ? [`${name}: ${numberText(missing)} пропуск${missing === 1 ? "" : "ов"}`] : []),
      ...(empty ? [`${name}: ${numberText(empty)} пустых строк`] : []),
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
      <header className="report-builder-head"><div><h2>Отчёт по источнику</h2><p>Выберите выводы EVIA, которые хотите включить в PDF.</p></div>
        <button type="button" aria-label="Закрыть отчёт" onClick={onClose}>✕</button></header>
      <div className="report-builder-controls">
        <div className="report-builder-selection"><h3>Расчёты и выводы EVIA</h3>
          {available.length ? <><div className="report-builder-selection-actions">
            <button type="button" onClick={() => setSelectedIds(available.map((entry) => entry.id))}>Выбрать все</button>
            <button type="button" onClick={() => setSelectedIds([])}>Снять выбор</button>
          </div>{available.map((entry) => <label key={entry.id} className="report-builder-choice">
            <input type="checkbox" checked={selectedIds.includes(entry.id)} onChange={(event) =>
              setSelectedIds((ids) => event.target.checked ? [...ids, entry.id] : ids.filter((id) => id !== entry.id))} />
            <span>{entry.question}</span></label>)}</> : <p>Для этого источника пока нет готовых ответов EVIA. Базовый отчёт можно сохранить уже сейчас.</p>}
        </div>
        <button type="button" className="report-builder-print" onClick={printReport}>Сохранить в PDF</button>
      </div>
    </div>
    <article className="report-document" aria-label="PDF-отчёт">
      <header className="report-document-header"><span>EVIA · АНАЛИТИЧЕСКИЙ ОТЧЁТ</span><h1>{source.name}</h1><p>Подготовлено {reportDate}</p></header>
      <section className="report-section"><h2>Краткая сводка</h2>
        <div className="report-facts">
          <div><span>Источник</span><strong>{source.source_type === "csv" ? "CSV" : "PostgreSQL"}</strong></div>
          <div><span>Строк</span><strong>{rowCount === null ? "Неизвестно" : numberText(rowCount)}</strong></div>
          <div><span>Столбцов</span><strong>{numberText(fields.length)}</strong></div>
          <div><span>Версия схемы</span><strong>{schema.version}</strong></div>
        </div>
        <p>Снимок данных: {source.snapshot_id ?? "не указан"}. Выбранных выводов EVIA: {selected.length}.</p>
        <p>Профиль качества: {profile?.coverage === "full" ? "Весь источник" : profile ? `Выборка из ${numberText(profile.sample_size)} строк` : "не загружен"}.</p>
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
        {rows.length ? <ReportTable columns={fields.map((field) => field.name)}
          rows={rows.slice(0, 5).map((row) => fields.map((field) => row[field.name]))}
          caption={`Показаны первые ${Math.min(rows.length, 5)} строки предпросмотра`} /> : <p>В предпросмотре нет строк.</p>}
        <p className="report-note">Предпросмотр не заменяет полный набор данных.</p>
      </section>
      <section className="report-section"><h2>Качество данных</h2>
        {profile ? <><p>Охват: {profile.coverage === "full" ? "Весь источник" : `выборка из ${numberText(profile.sample_size)} строк`}.</p>
          {problems.length ? <ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>
            : <p>В доступном профиле пропуски и пустые значения не обнаружены.</p>}
          <p className="report-note">Проверены пропуски и пустые значения; корректность содержимого и бизнес-правила отдельно не подтверждались.</p></>
          : <p>Профиль качества не загружен; делать вывод об отсутствии проблем нельзя.</p>}
        {source.import_report && <div className="report-import"><h3>Импорт CSV</h3>
          <p>Принято строк: {numberText(source.import_report.accepted_rows)}. Отклонено строк при импорте: {numberText(source.import_report.rejected_rows)}.</p>
          {source.import_report.warnings.length > 0 && <ul>{source.import_report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
        </div>}
      </section>
      {pie && <section className="report-section"><h2>Распределение: {pie.field}</h2>
        <PieChart slices={pie.slices} label={`Круговая диаграмма по полю ${pie.field}`} />
        <p className="report-note">Доли рассчитаны только по строкам предпросмотра ({numberText(rows.length)}), без пустых значений.</p></section>}
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
              {chart && <GeneratedDashboard dashboard={chart} scope={`report-${entry.id}-${resultIndex}`} />}
            </div>;
          })}
        </div>)}
      </section>}
      <footer className="report-document-footer">EVIA · {source.name} · {reportDate}</footer>
    </article>
  </div>;
}
