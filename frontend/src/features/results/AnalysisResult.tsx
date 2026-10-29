import type { Row, SourceSchema, ToolResult } from "../../api";
import type { Entry } from "../chat/types";
import { SafeMarkdown } from "../chat/SafeMarkdown";
import { ToolResults } from "./ToolResults";
import { EviaMascot } from "../../components/EviaMascot";
import { Dashboard } from "../analytics/Dashboard";
import { GeneratedDashboard, generatedChartFrom, generatedDashboardFrom } from "./GeneratedDashboard";
import { SavedDashboard, savedDashboardId } from "./SavedDashboard";

type DashboardInput = { rows: Row[]; schema: SourceSchema };

const isoDate = /^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/;

function normalizedType(type: unknown) {
  if (["integer", "number", "decimal"].includes(String(type))) return "number";
  if (["date", "datetime"].includes(String(type))) return String(type);
  return "string";
}

function inferredType(values: unknown[]) {
  if (values.every((value) => typeof value === "number")) return "number";
  if (values.every((value) => typeof value === "string" && isoDate.test(value) && !Number.isNaN(new Date(value).getTime()))) return "date";
  return "string";
}

function resultSchema(rows: Row[]): SourceSchema {
  const names = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return {
    source_id: "agent-result",
    version: 1,
    objects: [{
      object_id: "agent-result:table",
      name: "agent_result",
      object_type: "result_table",
      row_count: rows.length,
      fields: names.map((name) => {
        const values = rows.map((row) => row[name]).filter((value) => value !== null && value !== undefined && value !== "");
        return {
          name,
          inferred_type: values.length ? inferredType(values) : "unknown",
          nullable: values.length !== rows.length,
          is_identifier_candidate: false,
        };
      }),
    }],
  };
}

function queryResultInput(data: unknown): DashboardInput | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const result = data as { columns?: unknown; rows?: unknown };
  if (!Array.isArray(result.columns) || !Array.isArray(result.rows) || !result.rows.length) return null;
  const columns = result.columns.map((column) => column && typeof column === "object" ? column as { name?: unknown; data_type?: unknown } : null);
  if (!columns.length || columns.some((column) => typeof column?.name !== "string")) return null;
  if (!result.rows.every((row) => Array.isArray(row) && row.length === columns.length)) return null;
  const names = columns.map((column) => column!.name as string);
  const rows = result.rows.map((row) => Object.fromEntries(names.map((name, index) => [name, (row as unknown[])[index]])));
  return {
    rows,
    schema: {
      source_id: "agent-result",
      version: 1,
      objects: [{
        object_id: "agent-result:query", name: "agent_result", object_type: "result_table", row_count: rows.length,
        fields: columns.map((column) => ({
          name: column!.name as string,
          inferred_type: normalizedType(column!.data_type),
          nullable: rows.some((row) => row[column!.name as string] === null),
          is_identifier_candidate: false,
        })),
      }],
    },
  };
}

function tabularInput(result: ToolResult): DashboardInput | null {
  if (!result.ok) return null;
  if (Array.isArray(result.data) && result.data.length && result.data.every((row) => row !== null && typeof row === "object" && !Array.isArray(row))) {
    const rows = result.data as Row[];
    return { rows, schema: resultSchema(rows) };
  }
  return queryResultInput(result.data);
}

function scalarText(value: unknown, type: string) {
  if (value === null || value === undefined) return "Нет подходящих значений";
  if (typeof value === "number") return value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  if (typeof value === "string" && ["date", "datetime"].includes(type)) {
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}:\d{2}:\d{2}))?/.exec(value);
    if (match) return `${match[3]}.${match[2]}.${match[1]}${match[4] ? ` ${match[4]}` : ""}`;
  }
  return String(value);
}

export function AnalysisResult({ entry, onOpenChat }: { entry?: Entry; onOpenChat?: () => void }) {
  const generated = entry?.answer?.tool_results.map(generatedDashboardFrom).filter((item) => item !== null).at(-1);
  const savedId = entry?.answer?.tool_results.filter((item) => item.ok).map((item) =>
    item.tool_name === "compose_dashboard" || item.tool_name === "add_charts_to_dashboard"
      ? savedDashboardId(item.data) : null).filter((id) => id !== null).at(-1);
  const generatedCharts = entry?.answer?.tool_results.map(generatedChartFrom).filter((item) => item !== null) ?? [];
  const otherResults = entry?.answer?.tool_results.filter((item) =>
    !generatedDashboardFrom(item) && !generatedChartFrom(item) && !((item.tool_name === "compose_dashboard" || item.tool_name === "add_charts_to_dashboard") && savedDashboardId(item.data))) ?? [];
  const result = otherResults.map(tabularInput).find((input): input is DashboardInput => input !== null);
  const field = result?.schema.objects[0]?.fields[0];
  const scalar = result?.rows.length === 1 && result.schema.objects[0]?.fields.length === 1 && field
    ? { name: field.name, type: field.inferred_type, value: result.rows[0][field.name] }
    : null;
  const scalarLabel = scalar?.type === "datetime" && /\bAVG\s*\(/i.test(entry?.answer?.analysis?.sql ?? "")
    ? "Средняя дата/время" : scalar?.name.replaceAll("_", " ");
  const hasVisualResult = Boolean(result || generated || savedId || generatedCharts.length);
  return (
    <div className="analytics-section analysis-result">
      {(!result && !generated && !savedId && !generatedCharts.length || scalar) && <div className="analytics-title">
        <div>
          <span className="analytics-kicker">ОТ ВОПРОСА К ВЫВОДУ</span>
          <h2>Результат анализа</h2>
        </div>
      </div>}
      {entry?.answer ? (
        <>
          {(entry.answer.status === "error" || entry.answer.status === "clarification" || entry.answer.answer_kind === "demo") && <div className="analysis-provenance">
            {entry.answer.status === "error" ? "Запрос не выполнен" : entry.answer.status === "clarification" ? "Нужно уточнение" : "Демо-ответ"}
          </div>}
          {savedId ? <SavedDashboard id={savedId} /> : generated ? <GeneratedDashboard dashboard={generated} scope={`generated-${entry.id}`} />
            : generatedCharts.map((chart, index) => <GeneratedDashboard key={`${entry.id}-${index}`} dashboard={chart} scope={`chart-${entry.id}-${index}`} />)}
          {scalar && <section className="analysis-scalar" aria-label="Показатель">
            <span>{scalarLabel}</span>
            <strong>{scalarText(scalar.value, scalar.type)}</strong>
          </section>}
          {result && !scalar && <Dashboard
            title="Результат анализа"
            sourceLabel="Таблица, полученная инструментом EVIA"
            scope={`result-${entry.id}`}
            schema={result.schema}
            rows={result.rows}
            context="result"
          />}
          <p className="analysis-question">{entry.question}</p>
          {hasVisualResult ? onOpenChat && <button className="result-open-chat" type="button" onClick={onOpenChat}>Открыть ответ в чате</button> : <div className="analysis-answer" aria-label="Вывод EVIA">
            <SafeMarkdown>{entry.answer.answer || "Модель вернула пустой ответ."}</SafeMarkdown>
          </div>}
          {entry.answer.analysis?.sql && <details className="analysis-sql">
            <summary>Показать SQL</summary>
            <code>{entry.answer.analysis.sql}</code>
          </details>}
          {otherResults.length > 0 && (result || generated || savedId || generatedCharts.length ? (
            <details className="analysis-details">
              <summary>Таблица и детали расчёта</summary>
              <ToolResults results={otherResults} analysis={entry?.answer?.analysis} />
            </details>
          ) : <ToolResults results={otherResults} analysis={entry?.answer?.analysis} />)}
        </>
      ) : (
        <div className="analytics-empty">
          <EviaMascot
            state={
              entry?.state === "pending"
                ? "analyzing"
                : entry?.state === "error"
                  ? "error"
                  : "waiting"
            }
            size={100}
            decorative
          />
          <h3>
            {entry?.state === "pending"
              ? "EVIA изучает ваш вопрос"
              : entry?.state === "error"
                ? "Не удалось получить результат"
                : "Начните с вопроса"}
          </h3>
          <p>
            {entry?.state === "error"
              ? "Повторите вопрос в диалоге справа."
              : "Здесь появятся выводы и результаты вычислений из вашего диалога."}
          </p>
        </div>
      )}
    </div>
  );
}
