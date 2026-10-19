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
