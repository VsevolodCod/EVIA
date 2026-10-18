import type { Row, ToolResult } from "../../api";
import { DataTable } from "./DataTable";
import { Icon } from "../../components/Icon";

const titles: Record<string, string> = {
  list_sources: "Источники данных",
  preview_source: "Выборка данных",
  profile_source: "Профиль данных",
  get_schema: "Структура данных",
  execute_sql: "Результат расчёта",
  run_sql: "Результат расчёта",
};

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
      {results.map((result, i) => (
        <section className="tool-result" key={i}>
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
          {Array.isArray(result.data) &&
          result.data.every(
            (row) =>
              row !== null && typeof row === "object" && !Array.isArray(row),
          ) ? (
            <DataTable
              rows={result.data as Row[]}
              label={`Результат ${result.tool_name}`}
            />
          ) : result.data !== null && result.data !== undefined ? (
            <details>
              <summary>Технические данные · {result.tool_name}</summary>
              <pre>{JSON.stringify(result.data, null, 2)}</pre>
            </details>
          ) : result.ok ? (
            <p className="muted">Инструмент не вернул данные.</p>
          ) : null}
          {Array.isArray(result.data) && (
            <details className="tool-method">
              <summary>Об источнике результата</summary>
              <p>
                Инструмент: {result.tool_name}. Отображены строки, возвращённые
                сервером.
              </p>
            </details>
          )}
        </section>
      ))}
    </div>
  );
}
