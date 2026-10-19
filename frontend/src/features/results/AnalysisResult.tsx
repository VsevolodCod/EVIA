import type { Row, SourceSchema, ToolResult } from "../../api";
import type { Entry } from "../chat/types";
import { SafeMarkdown } from "../chat/SafeMarkdown";
import { ToolResults } from "./ToolResults";
import { EviaMascot } from "../../components/EviaMascot";
import { Dashboard } from "../analytics/Dashboard";

function tabularRows(result: ToolResult): Row[] | null {
  if (!result.ok || !Array.isArray(result.data) || !result.data.length) return null;
  return result.data.every((row) => row !== null && typeof row === "object" && !Array.isArray(row))
    ? result.data as Row[]
    : null;
}

function inferredType(values: unknown[]) {
  if (values.every((value) => typeof value === "number")) return "number";
  if (values.every((value) => typeof value === "string" && !Number.isNaN(new Date(value).getTime()))) return "date";
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

export function AnalysisResult({ entry }: { entry?: Entry }) {
  const result = entry?.answer?.tool_results.map(tabularRows).find((rows): rows is Row[] => rows !== null);
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
            schema={resultSchema(result)}
            rows={result}
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
