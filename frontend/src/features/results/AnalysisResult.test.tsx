import { render, screen } from "@testing-library/react";
import { AnalysisResult } from "./AnalysisResult";

it("builds a dashboard from one successful tabular tool result", () => {
  render(<AnalysisResult entry={{
    id: "answer-1",
    question: "Как менялись продажи?",
    state: "success",
    answer: {
      answer: "Продажи растут.",
      steps: 1,
      tool_results: [{
        tool_name: "run_sql",
        ok: true,
        data: [
          { month: "2026-01-01", category: "A", revenue: 120 },
          { month: "2026-02-01", category: "B", revenue: 180 },
        ],
      }],
    },
  }} />);

  expect(screen.getByRole("heading", { name: "Результат анализа" })).toBeInTheDocument();
  expect(screen.getByText("Строк в результате")).toBeInTheDocument();
  expect(screen.getByText("Ответ инструмента")).toBeInTheDocument();
  expect(screen.getByText("В ответе инструмента: 2 строки")).toBeInTheDocument();
  expect(screen.queryByText(/предпросмотре источника/)).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Динамика по полю month/ })).toBeInTheDocument();
  expect(screen.getByText("Продажи растут.")).toBeInTheDocument();
});

it("builds a dashboard from the QueryResult container returned by query_data", () => {
  render(<AnalysisResult entry={{
    id: "answer-query", question: "Как менялась выручка?", state: "success",
    answer: {
      answer: "Есть рост.", steps: 1,
      tool_results: [{
        tool_name: "query_data", ok: true,
        data: {
          columns: [
            { name: "month", data_type: "date", nullable: false },
            { name: "revenue", data_type: "decimal", nullable: false },
          ],
          rows: [["2026-01-01", "120.50"], ["2026-02-01", "180.00"]],
        },
      }],
    },
  }} />);

  expect(screen.getByRole("img", { name: /Динамика по полю month/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Распределение поля revenue/ })).toBeInTheDocument();
});

it("distinguishes computed SQL from a demo answer", () => {
  const entry = {
    id: "computed", question: "Сколько заказов?", state: "success" as const,
    answer: {
      answer: "orders: 2", steps: 1, request_id: "req-1", status: "answered" as const, answer_kind: "computed" as const,
      analysis: { intent: "count", sql: "SELECT COUNT(*) AS orders FROM source", explanation: "orders: 2" },
      tool_results: [{ tool_name: "query_data", ok: true, data: {
        columns: [{ name: "orders", data_type: "integer" }], rows: [[2]],
      } }],
    },
  };
  const { rerender } = render(<AnalysisResult entry={entry} />);
  expect(screen.getByText("Рассчитано по CSV")).toBeInTheDocument();
  expect(screen.getByText("SELECT COUNT(*) AS orders FROM source")).toBeInTheDocument();
  rerender(<AnalysisResult entry={{ ...entry, answer: { answer: "Тестовый ответ", steps: 1, answer_kind: "demo", tool_results: [] } }} />);
  expect(screen.getByText("Демо-ответ")).toBeInTheDocument();
  expect(screen.queryByText("SELECT COUNT(*) AS orders FROM source")).not.toBeInTheDocument();
  rerender(<AnalysisResult entry={{ ...entry, answer: { answer: "Не удалось выполнить запрос", steps: 1, status: "error", tool_results: [] } }} />);
  expect(screen.getByText("Запрос не выполнен")).toBeInTheDocument();
  rerender(<AnalysisResult entry={{ ...entry, answer: { answer: "Уточните вопрос", steps: 1, status: "clarification", tool_results: [] } }} />);
  expect(screen.getByText("Нужно уточнение")).toBeInTheDocument();
  rerender(<AnalysisResult entry={{ ...entry, answer: { answer: "Старый ответ", steps: 0, tool_results: [] } }} />);
  expect(screen.getByText("Ответ из истории")).toBeInTheDocument();
  rerender(<AnalysisResult entry={{ ...entry, answer: { answer: "orders: 2", steps: 1, answer_kind: "model", tool_results: entry.answer.tool_results } }} />);
  expect(screen.getByText("Рассчитано по данным")).toBeInTheDocument();
});

it("keeps the regular tool result for failed or non-tabular outputs", () => {
  render(<AnalysisResult entry={{
    id: "answer-2",
    question: "Покажи ошибку",
    state: "success",
    answer: {
      answer: "Расчёт не выполнился.",
      steps: 1,
      tool_results: [{ tool_name: "run_sql", ok: false, data: null, error: "Нет доступа" }],
    },
  }} />);

  expect(screen.getByRole("heading", { name: "Результат анализа" })).toBeInTheDocument();
  expect(screen.queryByText("Строк в выборке")).not.toBeInTheDocument();
  expect(screen.getByText("Нет доступа")).toBeInTheDocument();
});
