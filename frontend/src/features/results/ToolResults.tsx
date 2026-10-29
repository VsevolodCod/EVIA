import type { Answer, Row, ToolResult } from "../../api";
import { Icon } from "../../components/Icon";
import { ResultVisualization } from "./ResultVisualization";
import { HypothesisEvidence, isHypothesisEvidence } from "./HypothesisEvidence";
import { csvTableFrom, downloadCsv } from "./csvExport";
import type { ChartColumn } from "./resultChartModel";

const titles: Record<string, string> = {
  list_sources: "Источники данных",
  preview_source: "Выборка данных",
  profile_source: "Профиль данных",
  get_schema: "Структура данных",
  execute_sql: "Результат расчёта",
  run_sql: "Результат расчёта",
  compare_groups: "Сравнение групп",
  analyze_relationship: "Анализ связи",
};
const exportableTools = new Set(["query_data", "run_sql", "execute_sql"]);

function chartColumns(data: unknown): ChartColumn[] | undefined {
  if (!data || typeof data !== "object" || !("columns" in data) || !Array.isArray(data.columns)) return undefined;
  return data.columns.flatMap((column: unknown) => {
    if (!column || typeof column !== "object" || !("name" in column) || typeof column.name !== "string") return [];
    return [{ name: column.name,
      data_type: "data_type" in column && typeof column.data_type === "string" ? column.data_type : undefined,
      is_identifier_candidate: "is_identifier_candidate" in column && column.is_identifier_candidate === true,
    }];
  });
}

function tabularRows(data: unknown): Row[] | null {
  if (Array.isArray(data) && data.every((row) => row !== null && typeof row === "object" && !Array.isArray(row))) return data as Row[];
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const query = data as { columns?: unknown; rows?: unknown };
  if (!Array.isArray(query.columns) || !Array.isArray(query.rows)) return null;
  const names = query.columns.map((column) => column && typeof column === "object" ? (column as { name?: unknown }).name : null);
  if (!names.length || names.some((name) => typeof name !== "string") || !query.rows.every((row) => Array.isArray(row) && row.length === names.length)) return null;
  return query.rows.map((row) => Object.fromEntries((row as unknown[]).map((value, index) => [names[index] as string, value])));
}

function resultPassport(data: unknown) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const result = data as Record<string, unknown>;
  if (!Array.isArray(result.provenance) || !Array.isArray(result.rows)) return null;
  const origin = result.provenance.find((value) => value && typeof value === "object" && !Array.isArray(value)) as Record<string, unknown> | undefined;
  if (!origin || typeof origin.source_id !== "string" || typeof origin.snapshot_id !== "string") return null;
  return {
    source: origin.source_id,
    snapshot: origin.snapshot_id,
    schemaVersion: typeof origin.schema_version === "number" ? origin.schema_version : null,
    shown: result.rows.length,
    truncated: result.truncated === true,
  };
}

export function ToolResults({ results, analysis }: { results: ToolResult[]; analysis?: Answer["analysis"] }) {
  if (!results.length)
    return (
      <div className="empty-table">
        <Icon name="grid" size={28} />
        <p>Модель не вернула результаты инструментов</p>
        <span>Текст ответа находится в диалоге справа.</span>
      </div>
    );
  return (
    <div className="tool-results">
      {results.map((result, i) => {
        const rows = tabularRows(result.data);
        const csvTable = result.ok && exportableTools.has(result.tool_name) ? csvTableFrom(result.data) : null;
        const passport = result.ok && result.tool_name === "query_data" ? resultPassport(result.data) : null;
        const sql = results.filter((item) => item.tool_name === "query_data" && item.ok).length === 1
          ? analysis?.sql : null;
        const hypothesis = result.ok &&
          (result.tool_name === "compare_groups" || result.tool_name === "analyze_relationship") &&
          isHypothesisEvidence(result.data) ? result.data : null;
        return <section className="tool-result" key={i}>
          <div className="section-heading">
            <h3>{titles[result.tool_name] ?? "Результат инструмента"}</h3>
            <span className={`pill ${result.ok ? "" : "error-pill"}`}>
              {result.ok ? "Выполнено" : "Ошибка"}
            </span>
          </div>
          {!result.ok && (
            <p className="error-text">
              {result.error || "Инструмент не смог выполнить запрос."}
            </p>
          )}
          {csvTable && <div className="tool-export">
            <button type="button" onClick={() => downloadCsv(csvTable)}>Скачать CSV</button>
            {csvTable.truncated && <p>
              {csvTable.rows.length === 1
                ? "В CSV попадёт только 1 строка, возвращённая сервером. Результат усечён."
                : `В CSV попадут только ${csvTable.rows.length} строк, возвращённых сервером. Результат усечён.`}
            </p>}
          </div>}
          {passport && <details className="tool-method result-passport">
            <summary>Паспорт результата</summary>
            <dl>
              <div><dt>Источник</dt><dd>{passport.source}</dd></div>
              <div><dt>Снимок данных</dt><dd>{passport.snapshot}</dd></div>
              {passport.schemaVersion !== null && <div><dt>Версия схемы</dt><dd>{passport.schemaVersion}</dd></div>}
              <div><dt>Возвращено строк</dt><dd>{passport.shown}</dd></div>
              {sql && <div><dt>SQL</dt><dd><code>{sql}</code></dd></div>}
            </dl>
            {passport.truncated && <p>Показана только часть результата. Экспорт содержит только возвращённые строки.</p>}
          </details>}
          {hypothesis ? <HypothesisEvidence evidence={hypothesis} /> : rows ? (
            <ResultVisualization
              rows={rows}
              label={`Результат ${result.tool_name}`}
              columns={chartColumns(result.data)}
              copyableIdentifierColumns={result.tool_name === "list_sources" ? ["source_id", "snapshot_id"] : undefined}
            />
          ) : result.data !== null && result.data !== undefined ? (
            <details>
              <summary>Технические данные · {result.tool_name}</summary>
              <pre>{JSON.stringify(result.data, null, 2)}</pre>
            </details>
          ) : result.ok ? (
            <p className="muted">Инструмент не вернул данные.</p>
          ) : null}
          {rows && (
            <details className="tool-method">
              <summary>Об источнике результата</summary>
              <p>
                Инструмент: {result.tool_name}. Отображены строки, возвращённые
                сервером.
              </p>
            </details>
          )}
        </section>;
      })}
    </div>
  );
}
