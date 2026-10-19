import type { Row, SourceSchema, ToolResult } from "../../api";
import type { Entry } from "../chat/types";
import { SafeMarkdown } from "../chat/SafeMarkdown";
import { ToolResults } from "./ToolResults";
import { EviaMascot } from "../../components/EviaMascot";
import { Dashboard } from "../analytics/Dashboard";

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

export function AnalysisResult({ entry }: { entry?: Entry }) {
  const result = entry?.answer?.tool_results.map(tabularInput).find((input): input is DashboardInput => input !== null);
  return (
    <div className="analytics-section analysis-result">
      {!result && <div className="analytics-title">
        <div>
          <span className="analytics-kicker">ОТ ВОПРОСА К ВЫВОДУ</span>
          <h2>Результат анализа</h2>
        </div>
      </div>}
      {entry?.answer ? (
        <>
          {result && <Dashboard
            title="Результат анализа"
            sourceLabel="Таблица, полученная инструментом EVIA"
            scope={`result-${entry.id}`}
            schema={result.schema}
            rows={result.rows}
            context="result"
          />}
          <p className="analysis-question">{entry.question}</p>
          <section className="analysis-answer" aria-label="Вывод EVIA">
            <span className="answer-signature">EVIA</span>
            <SafeMarkdown>
              {entry.answer.answer || "Модель вернула пустой ответ."}
            </SafeMarkdown>
          </section>
          {entry.answer.tool_results.length > 0 && (
            <ToolResults results={entry.answer.tool_results} />
          )}
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
