import type { Answer, Row, ToolResult } from "../../api";
import { useLanguage } from "../../language";
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
  const { t } = useLanguage();
  const englishTitles: Record<string, string> = { list_sources: "Data sources", preview_source: "Data sample", profile_source: "Data profile", get_schema: "Data structure", execute_sql: "Calculation result", run_sql: "Calculation result", compare_groups: "Group comparison", analyze_relationship: "Relationship analysis" };
  if (!results.length)
    return (
      <div className="empty-table">
        <Icon name="grid" size={28} />
        <p>{t("Модель не вернула результаты инструментов", "The model returned no tool results")}</p>
        <span>{t("Текст ответа находится в диалоге справа.", "The answer is in the chat.")}</span>
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
            <h3>{t(titles[result.tool_name] ?? "Результат инструмента", englishTitles[result.tool_name] ?? "Tool result")}</h3>
            <span className={`pill ${result.ok ? "" : "error-pill"}`}>
              {result.ok ? t("Выполнено", "Completed") : t("Ошибка", "Error")}
            </span>
          </div>
          {!result.ok && (
            <p className="error-text">
              {result.error || t("Инструмент не смог выполнить запрос.", "The tool could not complete the request.")}
            </p>
          )}
          {csvTable && <div className="tool-export">
            <button type="button" onClick={() => downloadCsv(csvTable)}>{t("Скачать CSV", "Download CSV")}</button>
            {csvTable.truncated && <p>
              {csvTable.rows.length === 1
                ? t("В CSV попадёт только 1 строка, возвращённая сервером. Результат усечён.", "The CSV contains only the 1 row returned by the server. The result is truncated.")
                : t(`В CSV попадут только ${csvTable.rows.length} строк, возвращённых сервером. Результат усечён.`, `The CSV contains only the ${csvTable.rows.length} rows returned by the server. The result is truncated.`)}
            </p>}
          </div>}
          {passport && <details className="tool-method result-passport">
            <summary>{t("Паспорт результата", "Result details")}</summary>
            <dl>
              <div><dt>{t("Источник", "Source")}</dt><dd>{passport.source}</dd></div>
              <div><dt>{t("Снимок данных", "Data snapshot")}</dt><dd>{passport.snapshot}</dd></div>
              {passport.schemaVersion !== null && <div><dt>{t("Версия схемы", "Schema version")}</dt><dd>{passport.schemaVersion}</dd></div>}
              <div><dt>{t("Возвращено строк", "Rows returned")}</dt><dd>{passport.shown}</dd></div>
              {sql && <div><dt>SQL</dt><dd><code>{sql}</code></dd></div>}
            </dl>
            {passport.truncated && <p>{t("Показана только часть результата. Экспорт содержит только возвращённые строки.", "Only part of the result is shown. The export contains only returned rows.")}</p>}
          </details>}
          {hypothesis ? <HypothesisEvidence evidence={hypothesis} /> : rows ? (
            <ResultVisualization
              rows={rows}
              label={t(`Результат ${result.tool_name}`, `Result of ${result.tool_name}`)}
              columns={chartColumns(result.data)}
              truncated={Boolean(result.data && typeof result.data === "object" && !Array.isArray(result.data) && "truncated" in result.data && result.data.truncated === true)}
              copyableIdentifierColumns={result.tool_name === "list_sources" ? ["source_id", "snapshot_id"] : undefined}
            />
          ) : result.data !== null && result.data !== undefined ? (
            <details>
              <summary>{t("Технические данные", "Technical details")} · {result.tool_name}</summary>
              <pre>{JSON.stringify(result.data, null, 2)}</pre>
            </details>
          ) : result.ok ? (
            <p className="muted">{t("Инструмент не вернул данные.", "The tool returned no data.")}</p>
          ) : null}
          {rows && (
            <details className="tool-method">
              <summary>{t("Об источнике результата", "About the result source")}</summary>
              <p>
                {t("Инструмент", "Tool")}: {result.tool_name}. {t("Отображены строки, возвращённые сервером.", "Showing rows returned by the server.")}
              </p>
            </details>
          )}
        </section>;
      })}
    </div>
  );
}
