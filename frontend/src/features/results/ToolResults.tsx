import type { Row, ToolResult } from "../../api";
import { Icon } from "../../components/Icon";
import { ResultVisualization } from "./ResultVisualization";

const titles: Record<string, string> = {
  list_sources: "Источники данных",
  preview_source: "Выборка данных",
  profile_source: "Профиль данных",
  get_schema: "Структура данных",
  execute_sql: "Результат расчёта",
  run_sql: "Результат расчёта",
};

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
        const rows = tabularRows(result.data);
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
          {rows ? (
            <ResultVisualization
              rows={rows}
              label={`Результат ${result.tool_name}`}
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
