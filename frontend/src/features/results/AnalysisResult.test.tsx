import { fireEvent, render, screen } from "@testing-library/react";
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
  expect(screen.getByText("Рассчитано по источнику")).toBeInTheDocument();
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

it("shows a single computed timestamp as a result instead of an empty dashboard", () => {
  render(<AnalysisResult entry={{
    id: "average-date", question: "Среднее первого ответа?", state: "success",
    answer: {
      answer: "Средняя дата/время: 07.10.2025 01:36:06", steps: 1,
      answer_kind: "computed", status: "answered",
      analysis: { intent: "average", sql: 'SELECT AVG(TRY_CAST("Первый ответ (МСК)" AS TIMESTAMP)) AS avg_first_answer FROM source', explanation: "" },
      tool_results: [{ tool_name: "query_data", ok: true, data: {
        columns: [{ name: "avg_first_answer", data_type: "datetime" }],
        rows: [["2025-10-07T01:36:06"]],
      } }],
    },
  }} />);

  expect(screen.getByText("Средняя дата/время", { selector: ".analysis-scalar span" })).toBeInTheDocument();
  expect(screen.getByText("07.10.2025 01:36:06", { selector: ".analysis-scalar strong" })).toBeInTheDocument();
  expect(screen.queryByText("Строк в результате")).not.toBeInTheDocument();
  expect(screen.queryByText("Заполнено ячеек")).not.toBeInTheDocument();
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

it("renders a computed dashboard with KPI, line, colors and PDF export", () => {
  const originalPrint = window.print;
  const print = vi.fn();
  window.print = print;
  try {
    render(<AnalysisResult entry={{
      id: "generated-1", question: "Создай дашборд выручки", state: "success",
      answer: {
        answer: "Построено карточек: 2.", steps: 1, status: "answered", answer_kind: "computed",
        tool_results: [{ tool_name: "create_dashboard", ok: true, data: {
          version: 1, title: "Продажи", palette: ["#518ed5", "#ddaa65"], cards: [
            { id: "total", type: "kpi", title: "Выручка", status: "success",
              definition: { type: "kpi", field: { source_id: "sales-1", field: "revenue" }, aggregate: "sum", filters: [] },
              data: { value: "301.0", aggregate: "sum", format: { type: "number", decimals: 1 } } },
            { id: "monthly", type: "line", title: "По месяцам", status: "success", data: {
              x: { field: "month", label: "Месяц", type: "category" },
              y: { field: "revenue", label: "Выручка", aggregate: "sum", format: { type: "number", decimals: 1 } },
              points: [{ x: "2026-01", y: "120.5" }, { x: "2026-02", y: "180.5" }],
            } },
          ],
        } }],
      },
    }} />);

    expect(screen.getByRole("heading", { name: "Продажи" })).toBeInTheDocument();
    expect(screen.getByText("301,0")).toBeInTheDocument();
    expect(screen.getByText("Паспорт расчёта")).toBeInTheDocument();
    expect(screen.getByText("SUM(revenue)")).toBeInTheDocument();
    expect(screen.getByText("sales-1")).toBeInTheDocument();
    expect(screen.getByText("Весь источник без фильтров")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /По месяцам/ })).toBeInTheDocument();
    expect(screen.getByText("2026-01")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Цвета" }));
    expect(screen.getByText("Цвета графиков")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Экспорт PDF" }));
    expect(print).toHaveBeenCalledOnce();
    expect(screen.queryByText(/\"version\"/)).not.toBeInTheDocument();
  } finally {
    window.print = originalPrint;
  }
});

it("shows the successful dashboard after a failed first attempt", () => {
  render(<AnalysisResult entry={{
    id: "generated-retry", question: "Построй дашборд", state: "success",
    answer: { answer: "Построено карточек: 1.", steps: 2, status: "answered", answer_kind: "computed",
      tool_results: [
        { tool_name: "create_dashboard", ok: true, data: { version: 1, title: "Неудачный вариант", cards: [
          { id: "failed", type: "kpi", title: "Ошибка", status: "error", error: { code: "unsupported_type" } },
        ] } },
        { tool_name: "create_dashboard", ok: true, data: { version: 1, title: "Готовый дашборд", cards: [
          { id: "success", type: "kpi", title: "Выручка", status: "success", data: { value: "301.0" } },
        ] } },
      ] },
  }} />);
  expect(screen.getByRole("heading", { name: "Готовый дашборд" })).toBeInTheDocument();
  expect(screen.getByText("301,0")).toBeInTheDocument();
  expect(screen.queryByText("Неудачный вариант")).not.toBeInTheDocument();
});
