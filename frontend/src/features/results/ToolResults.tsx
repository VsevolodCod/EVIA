import type { Row, ToolResult } from "../../api";
import { Icon } from "../../components/Icon";
import { ResultVisualization } from "./ResultVisualization";
import { csvTableFrom, downloadCsv } from "./csvExport";
import type { ChartColumn } from "./resultChartModel";

const titles: Record<string, string> = {
  list_sources: "Источники данных",
  preview_source: "Выборка данных",
  profile_source: "Профиль данных",
  get_schema: "Структура данных",
  execute_sql: "Результат расчёта",
  run_sql: "Результат расчёта",
  continue_analysis: "Продолжение анализа",
};
const exportableTools = new Set(["query_data", "run_sql", "execute_sql", "continue_analysis"]);

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

export function ToolResults({ results }: { results: ToolResult[] }) {
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
        const continuation = result.tool_name === "continue_analysis" && result.data && typeof result.data === "object"
          ? result.data as { query_result?: unknown; presentation?: unknown } : null;
        const data = continuation?.query_result ?? result.data;
        const initialView = continuation?.presentation === "bar" || continuation?.presentation === "line" ? continuation.presentation : "table";
        const resultId = data && typeof data === "object" && "result_id" in data && typeof data.result_id === "string" ? data.result_id : String(i);
        const rows = tabularRows(data);
        const csvTable = result.ok && exportableTools.has(result.tool_name) ? csvTableFrom(data) : null;
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
          {rows ? (
            <ResultVisualization
              key={`${resultId}:${initialView}`}
              rows={rows}
              label={`Результат ${result.tool_name}`}
              columns={chartColumns(data)}
              initialView={initialView}
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
