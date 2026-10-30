import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import App from "./App";
const source = (id: string) => ({
  source_id: id,
  name: `Источник ${id}`,
  source_type: "csv",
  status: "available",
  created_at: "2026-10-16",
  schema_version: 1,
});

function mockCsvUpload(result: object, automatic = true) {
  const requests: FakeXHR[] = [];
  class FakeXHR {
    upload: { onprogress?: (event: { lengthComputable: boolean; loaded: number; total: number }) => void; onload?: () => void } = {};
    status = 200;
    responseText = JSON.stringify(result);
    onload?: () => void;
    open = vi.fn();
    setRequestHeader = vi.fn();
    send = vi.fn(() => {
      requests.push(this);
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
      if (automatic) queueMicrotask(() => this.respond());
    });
    respond() {
      this.upload.onload?.();
      this.onload?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return requests;
}
const schema = (id: string) => ({
  source_id: id,
  version: 1,
  objects: [
    {
      object_id: id + ":table",
      name: id,
      object_type: "csv_table",
      fields: [
        {
          name: "product",
          inferred_type: "string",
          nullable: false,
          is_identifier_candidate: false,
        },
      ],
      row_count: 1,
    },
  ],
});
const profile = {
  sample_size: 1,
  sample_limit: 500,
  columns: {
    product: {
      sample_non_null_count: 1,
      sample_null_count: 0,
      distinct_sample_values: 1,
      top_values: [{ value: "real", count: 1 }],
    },
  },
  note: "Sample only",
};
function setup(
  ask?: (init?: RequestInit, url?: string) => Promise<Response>,
  preview?: (url: string) => Promise<Response>,
) {
  let nextChat = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url === "/health")
        return Promise.resolve(
          Response.json({ status: "ok", llm_provider: "mock" }),
        );
      if (url === "/sources")
        return Promise.resolve(Response.json([source("A"), source("B")]));
      if (url === "/sources/postgresql/status")
        return Promise.resolve(Response.json({ configured: false, connected: false }));
      if (url === "/chats?limit=100") return Promise.resolve(Response.json([]));
      if (url === "/chats") return Promise.resolve(Response.json({
        chat_id: `chat-${++nextChat}`,
        title: "Новый чат",
        created_at: "2026-10-18T08:00:00Z",
        updated_at: "2026-10-18T08:00:00Z",
      }));
      if (url.startsWith("/agent/chat?") && ask) return ask(init, url).then(async (response) =>
        response.ok ? Response.json({ ...await response.json(), chat_id: new URL(url, "http://test").searchParams.get("chat_id") }) : response);
      if (url.endsWith("/schema"))
        return Promise.resolve(Response.json(schema(url.split("/")[2])));
      if (url.includes("/preview"))
        return preview
          ? preview(url)
          : Promise.resolve(
              Response.json([{ product: `row-${url.split("/")[2]}` }]),
            );
      if (url.endsWith("/profile"))
        return Promise.resolve(Response.json(profile));
      return Promise.reject(new Error("Unexpected route " + url));
    }),
  );
}
async function select(id: string) {
  fireEvent.click(
    await screen.findByRole("button", { name: `Источник ${id}` }),
  );
}
async function ask(question: string) {
  const previousCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/agent/chat?")).length;
  fireEvent.change(screen.getByRole("textbox", { name: "Ваш вопрос" }), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Отправить вопрос" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/agent/chat?")).length).toBeGreaterThan(previousCalls));
}

it("greets visitors and highlights PostgreSQL selection without a marker dot", async () => {
  setup();
  render(<App />);
  expect((await screen.findAllByLabelText("Приветствие EVIA")).length).toBeGreaterThan(0);
  expect(document.querySelector(".mobile-home-greeting .evia-greeting-block")).toBeInTheDocument();
  await select("A");
  expect(document.querySelector(".selection-dot")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Подключить PostgreSQL" }));
  expect(screen.getByRole("button", { name: "Подключить PostgreSQL" })).toHaveAttribute("aria-pressed", "true");
});
it("shows an incomplete model response as a retryable error", async () => {
  setup(() => Promise.resolve(Response.json({
    answer: "Ответ модели прервался из-за лимита генерации.",
    status: "error",
    steps: 2,
    tool_results: [],
  })));
  render(<App />);
  await select("A");
  await ask("Что в данных?");
  expect(await screen.findByText("Ответ модели прервался из-за лимита генерации.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить вопрос" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Результаты инструментов/ })).not.toBeInTheDocument();
});

it("opens a real import flow and settings without a fictional analysis wizard or guest profile", async () => {
  setup();
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  expect(screen.getByRole("heading", { name: "Добавьте CSV" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "Новый анализ" })).not.toBeInTheDocument();
  expect(screen.queryByText("Гостевой доступ")).not.toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Мобильная навигация" }).querySelectorAll("button")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Открыть настройки" }));
  expect(screen.getByRole("dialog", { name: "Настройки" })).toBeInTheDocument();
});

it("attaches a selected saved report to one source conversation and clears it on source change", async () => {
  setup(() => Promise.resolve(Response.json({ answer: "Готово", steps: 1, tool_results: [] })));
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url: string | URL | Request, init?: RequestInit) => {
    if (String(url).startsWith("/dashboards/ids")) return Promise.resolve(Response.json({ dashboard_ids: ["report-1"] }));
    if (url === "/dashboards/report-1") return Promise.resolve(Response.json({ success: true, dashboard: {
      id: "report-1", title: "Отчёт продаж", version: 1, charts: [{ chart_id: "total", position: 0 }],
    } }));
    if (url === "/dashboards/report-1/build") return Promise.resolve(Response.json({ success: true,
      dashboard: { id: "report-1", title: "Отчёт продаж", version: 1, charts: [{ chart_id: "total", position: 0 }] },
      charts: [{ chart_id: "total", position: 0, success: true, chart_type: "kpi", definition: { type: "kpi", title: "Выручка" }, result: { value: 30 } }],
    }));
    return original(url, init);
  });
  render(<App />);
  await select("A");
  fireEvent.click(screen.getByRole("button", { name: /Сохранённые отчёты/ }));
  fireEvent.click(await screen.findByRole("button", { name: /Отчёт продаж/ }));
  fireEvent.click(screen.getByRole("button", { name: /Обсудить этот отчёт/ }));
  expect(screen.getByLabelText("Прикреплённый отчёт")).toHaveTextContent("Отчёт продаж");
  await ask("Поясни отчёт");
  const calls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/agent/chat?"));
  expect(JSON.parse(String(calls.at(-1)![1]?.body))).toMatchObject({ dashboard_id: "report-1", source_ids: ["A"] });
  await select("B");
  expect(screen.queryByLabelText("Прикреплённый отчёт")).not.toBeInTheDocument();
  await ask("Вопрос по B");
  const next = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/agent/chat?"));
  expect(JSON.parse(String(next.at(-1)![1]?.body))).toEqual({ question: "Вопрос по B", source_ids: ["B"] });
});
it("keeps late answers and history bound to their source", async () => {
  let now = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  let finish!: (r: Response) => void;
  setup(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(<App />);
  await select("A");
  await ask("Вопрос A");
  await select("B");
  now = 5000;
  await act(async () =>
    finish(
      Response.json({ answer: "Ответ только A", steps: 1, tool_results: [] }),
    ),
  );
  expect(screen.queryByText("Ответ только A")).not.toBeInTheDocument();
  expect(screen.queryByText(/Ответ за/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Вопрос A" }),
  ).not.toBeInTheDocument();
  await select("A");
  expect(await screen.findByText("Ответ только A")).toBeInTheDocument();
  expect(screen.getByText("Ответ за 4,0 с")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Вопрос A" })).toBeInTheDocument();
});
it("reopens a server conversation after reload without mixing it into another source", async () => {
  // A stale browser cache must not move a server-bound chat to another source.
  localStorage.setItem("evia.chat-sources.v1", JSON.stringify({ "chat-a": "B" }));
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([source("A"), source("B")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "chat-a", title: "Продажи по месяцам", source_id: "A", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/chat-a?limit=50") return Promise.resolve(Response.json({
      chat_id: "chat-a",
      title: "Продажи по месяцам",
      source_id: "A",
      messages: [
        { message_id: "question-a", role: "user", content: "Покажи продажи", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "trace-a", role: "assistant", content: "Сначала проверю данные", tool_calls: [{ id: "call-a" }], created_at: "2026-10-18T08:00:00Z" },
        { message_id: "tool-a", role: "tool", content: "{\"rows\":[[300]]}", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "continue-a", role: "user", content: "Продолжи ответ точно с места обрыва, без повторения уже написанного.", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "answer-a", role: "assistant", content: "Продажи выросли.", created_at: "2026-10-18T08:00:01Z", analysis_payload: {
          version: 1, response: {
            answer: "Продажи выросли.", steps: 1, request_id: "saved-request", answer_kind: "computed",
            analysis: { intent: "sales", sql: "SELECT SUM(revenue) FROM sales", explanation: "Сумма продаж" },
            timing: { elapsed_ms: 1200, llm_ms: 600, tools_ms: 400, calls: [] },
            tool_results: [
              { tool_name: "query_data", ok: true, data: { columns: [{ name: "total", data_type: "number" }], rows: [[300]] } },
              { tool_name: "create_dashboard", ok: true, error: null,
                data: { version: 1, title: "Сохранённый дашборд", cards: [{ id: "revenue", type: "kpi", title: "Выручка", status: "success", data: { value: "301.0" } }] } },
            ],
          },
        } },
      ],
      total_messages: 5,
      next_offset: null,
      next_before: null,
      has_more: false,
    }));
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema(url.split("/")[2])));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "row" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await select("A");
  fireEvent.click(await screen.findByRole("button", { name: "Покажи продажи" }));
  expect(
    await within(
      screen.getByRole("complementary", { name: "Чат с EVIA" }),
    ).findByText("Продажи выросли."),
  ).toBeInTheDocument();
  expect(await screen.findByText("Сохранённый дашборд")).toBeInTheDocument();
  expect(screen.getByText("Ответ за 1,2 с")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть результат" }));
  expect(await screen.findByText("SELECT SUM(revenue) FROM sales")).toBeInTheDocument();
  await select("B");
  expect(screen.queryByText("Продажи выросли.")).not.toBeInTheDocument();
});

it("reopens an unanswered question with retry instead of a successful answer", async () => {
  localStorage.setItem("evia.chat-sources.v1", JSON.stringify({ "chat-a": "A" }));
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([source("A")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "chat-a", title: "Вопрос о данных", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/chat-a?limit=50") return Promise.resolve(Response.json({
      chat_id: "chat-a", title: "Вопрос о данных",
      messages: [{ message_id: "question-a", role: "user", content: "Сколько строк?", created_at: "2026-10-18T08:00:00Z" }],
      total_messages: 1, next_offset: null, next_before: null, has_more: false,
    }));
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema("A")));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "row" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await select("A");
  fireEvent.click(await screen.findByRole("button", { name: "Сколько строк?" }));
  expect(await screen.findByRole("button", { name: "Повторить вопрос" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Результаты инструментов/ })).not.toBeInTheDocument();
});

it("opens an archived result after its source is no longer available", async () => {
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([source("A")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "archived", title: "Итог удалённого CSV", source_id: "deleted-source", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/archived?limit=50") return Promise.resolve(Response.json({
      chat_id: "archived", title: "Итог удалённого CSV", source_id: "deleted-source",
      messages: [
        { message_id: "old-question", role: "user", content: "Какая сумма?", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "old-answer", role: "assistant", content: "300", created_at: "2026-10-18T08:00:01Z", analysis_payload: {
          version: 1, response: { answer: "300", steps: 1, tool_results: [], timing: { elapsed_ms: 750, llm_ms: 300, tools_ms: 200, calls: [] } },
        } },
      ], total_messages: 2, next_offset: null, next_before: null, has_more: false,
    }));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Архив: Итог удалённого CSV" }));
  expect(await screen.findByText("300")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeDisabled();
  expect(screen.getByText("Ответ за 0,8 с")).toBeInTheDocument();
});

it("continues an unbound legacy chat only after the user explicitly chooses a source", async () => {
  const sent: { url: string; body: { source_ids: string[] } }[] = [];
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([source("A")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "legacy", title: "Старый диалог", source_id: null, created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/legacy?limit=50") return Promise.resolve(Response.json({
      chat_id: "legacy", title: "Старый диалог", source_id: null,
      messages: [
        { message_id: "old-question", role: "user", content: "Что было?", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "old-answer", role: "assistant", content: "Только текст", created_at: "2026-10-18T08:00:01Z" },
      ], total_messages: 2, next_offset: null, next_before: null, has_more: false,
    }));
    if (url === "/agent/chat?chat_id=legacy") {
      sent.push({ url, body: JSON.parse(String(init?.body)) });
      return Promise.resolve(Response.json({ chat_id: "legacy", answer: "Продолжение", steps: 1, tool_results: [] }));
    }
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema("A")));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "row" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const oldChat = await screen.findByRole("button", { name: "Без источника: Старый диалог" });
  expect(screen.getAllByRole("heading", { name: "История диалогов" })).toHaveLength(1);
  expect(screen.queryByRole("heading", { name: "Диалоги без источника" })).not.toBeInTheDocument();
  expect(screen.queryByText("Нет диалогов")).not.toBeInTheDocument();
  fireEvent.click(oldChat);
  expect(await screen.findByText("Только текст")).toBeInTheDocument();
  expect(screen.getByText("Для продолжения этого старого диалога выберите источник в левой панели.")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeDisabled();
  await select("A");
  await ask("Продолжи");
  expect(await screen.findByText("Продолжение")).toBeInTheDocument();
  expect(sent).toEqual([{ url: "/agent/chat?chat_id=legacy", body: { question: "Продолжи", source_ids: ["A"] } }]);
});

it("keeps readable old chats visible when the selected source history fails", async () => {
  setup();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url: string | URL | Request, init?: RequestInit) => {
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "broken", title: "Текущий", source_id: "A", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
      { chat_id: "old", title: "Старый", source_id: null, created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/broken?limit=50") return Promise.resolve(new Response(null, { status: 500 }));
    return original(url, init);
  });
  render(<App />);
  await select("A");
  expect(await screen.findByRole("button", { name: "Повторить загрузку истории" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Без источника: Старый" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "История диалогов" })).toHaveLength(1);
});

it("silently forgets a stale local chat mapping when its server history is gone", async () => {
  localStorage.setItem("evia.chat-sources.v1", JSON.stringify({ "chat-a": "A" }));
  const fetcher = vi.fn((url: string) => {
    if (url === "/sources") return Promise.resolve(Response.json([source("A")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "chat-a", title: "Старый диалог", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:00:00Z" },
    ]));
    if (url === "/chats/chat-a?limit=50") return Promise.resolve(new Response(null, { status: 404 }));
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema("A")));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "row" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await select("A");

  await waitFor(() =>
    expect(localStorage.getItem("evia.chat-sources.v1")).toBe("{}"),
  );
  expect(screen.queryByText("Источник больше не доступен. Обновите список источников.")).not.toBeInTheDocument();
});
it("loads an older page of the reopened server conversation", async () => {
  localStorage.setItem("evia.chat-sources.v1", JSON.stringify({ "chat-a": "A" }));
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([source("A")]));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([
      { chat_id: "chat-a", title: "История продаж", created_at: "2026-10-18T08:00:00Z", updated_at: "2026-10-18T08:01:00Z" },
    ]));
    if (url === "/chats/chat-a?limit=50") return Promise.resolve(Response.json({
      chat_id: "chat-a", title: "История продаж",
      messages: [
        { message_id: "question-latest", role: "user", content: "Новый вопрос", created_at: "2026-10-18T08:01:00Z" },
        { message_id: "answer-latest", role: "assistant", content: "Новый ответ", created_at: "2026-10-18T08:01:01Z" },
      ], total_messages: 4, next_offset: 2, next_before: 2, has_more: true,
    }));
    if (url === "/chats/chat-a?limit=50&before=2") return Promise.resolve(Response.json({
      chat_id: "chat-a", title: "История продаж",
      messages: [
        { message_id: "question-old", role: "user", content: "Старый вопрос", created_at: "2026-10-18T08:00:00Z" },
        { message_id: "answer-old", role: "assistant", content: "Старый ответ", created_at: "2026-10-18T08:00:01Z" },
      ], total_messages: 4, next_offset: null, next_before: null, has_more: false,
    }));
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema(url.split("/")[2])));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "row" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await select("A");
  fireEvent.click(await screen.findByRole("button", { name: "Новый вопрос" }));
  expect(
    await within(
      screen.getByRole("complementary", { name: "Чат с EVIA" }),
    ).findByText("Новый ответ"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Показать предыдущие сообщения" }));
  expect(
    await within(
      screen.getByRole("complementary", { name: "Чат с EVIA" }),
    ).findByText("Старый ответ"),
  ).toBeInTheDocument();
});
it("ignores late source previews after switching source", async () => {
  let finish!: (r: Response) => void;
  setup(undefined, (url) =>
    url.includes("/A/")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(Response.json([{ product: "row-B" }])),
  );
  render(<App />);
  await select("A");
  await select("B");
  fireEvent.click(screen.getByRole("button", { name: /^Данные$/ }));
  expect(await screen.findByText("row-B")).toBeInTheDocument();
  await act(async () => finish(Response.json([{ product: "stale-A" }])));
  expect(screen.queryByText("stale-A")).not.toBeInTheDocument();
});
it("retries a failed question with its original source and displays the response", async () => {
  let calls = 0;
  setup(async () =>
    ++calls === 1
      ? new Response("failed", { status: 502 })
      : Response.json({ answer: "Повтор успешен", steps: 1, tool_results: [] }),
  );
  render(<App />);
  await select("A");
  await ask("Повтори запрос");
  fireEvent.click(
    await screen.findByRole("button", { name: "Повторить вопрос" }),
  );
  expect(await screen.findByText("Повтор успешен")).toBeInTheDocument();
  expect(calls).toBe(2);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === "/chats")).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/agent/chat?")).map(([url]) => url))
    .toEqual(["/agent/chat?chat_id=chat-1", "/agent/chat?chat_id=chat-1"]);
});

it("continues one conversation, resumes an older one, and isolates sources", async () => {
  const sent: { url?: string; question: string; source_ids: string[] }[] = [];
  setup(async (init, url) => {
    const body = JSON.parse(String(init?.body));
    sent.push({ url, ...body });
    return Response.json({ answer: `Ответ: ${body.question}`, steps: 1, tool_results: [] });
  });
  render(<App />);
  await select("A");
  await ask("Первый");
  await screen.findByText("Ответ: Первый");
  await ask("Уточнение");
  await screen.findByText("Ответ: Уточнение");
  expect(screen.getByText("Ответ: Первый")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Уточнение" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  await select("A");
  await ask("Другой диалог");
  await screen.findByText("Ответ: Другой диалог");
  expect(screen.queryByText("Ответ: Первый")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Первый" }));
  expect(within(screen.getByRole("complementary", { name: "Чат с EVIA" })).getByText("Ответ: Уточнение")).toBeInTheDocument();
  await ask("Продолжение");
  await within(screen.getByRole("complementary", { name: "Чат с EVIA" })).findByText("Ответ: Продолжение");
  await select("B");
  await ask("Вопрос B");
  await screen.findByText("Ответ: Вопрос B");
  await select("A");
  expect(screen.queryByText("Ответ: Вопрос B")).not.toBeInTheDocument();
  expect(sent.map((s) => s.url)).toEqual([
    "/agent/chat?chat_id=chat-1", "/agent/chat?chat_id=chat-1", "/agent/chat?chat_id=chat-2",
    "/agent/chat?chat_id=chat-1", "/agent/chat?chat_id=chat-3",
  ]);
  expect(sent.map((s) => s.source_ids)).toEqual([["A"], ["A"], ["A"], ["A"], ["B"]]);
});

it("returns to the CSV start screen without removing connected sources", async () => {
  setup();
  render(<App />);
  await select("A");

  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));

  expect(
    await screen.findByRole("heading", { name: "Добавьте CSV" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Источник A" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeDisabled();
});

it("provides mobile navigation for sources, analytics, and chat", async () => {
  setup();
  render(<App />);

  expect(await screen.findByRole("navigation", { name: "Мобильная навигация" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Источники" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "Рабочее пространство" }));
  expect(screen.getByRole("button", { name: "Рабочее пространство" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "Чат" }));
  expect(screen.getByRole("button", { name: "Чат" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "Источники" }));
  expect(screen.getByRole("button", { name: "Источники" })).toHaveAttribute("aria-pressed", "true");
});

it("opens the analysis from a source and returns to the mobile home", async () => {
  setup();
  render(<App />);

  await select("A");
  expect(screen.getByRole("button", { name: "Рабочее пространство" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(screen.getByRole("main")).getByRole("button", { name: "Назад к источникам" }));
  expect(screen.getByRole("button", { name: "Источники" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Источник A" })).toBeInTheDocument();
});

it("opens a separate CSV upload screen from the home action", async () => {
  setup();
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));

  expect(screen.getByRole("button", { name: "Рабочее пространство" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("heading", { name: "Добавьте CSV" })).toBeInTheDocument();
});

it("previews a selected mobile CSV before uploading it", async () => {
  setup();
  const uploads = mockCsvUpload(source("C"));
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));

  fireEvent.change(screen.getByLabelText("Загрузить CSV"), {
    target: { files: [new File(["id\n1"], "orders.csv", { type: "text/csv" })] },
  });

  expect(screen.getByText("orders.csv")).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => url === "/sources/csv")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Загрузить файл" }));
  await waitFor(() => expect(uploads).toHaveLength(1));
});

it("opens a dismissible CSV sheet without fictitious analysis steps", async () => {
  setup();
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  expect(screen.queryByRole("dialog", { name: "Новый анализ" })).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "Загрузка CSV" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Закрыть загрузку CSV" }));
  expect(screen.queryByRole("dialog", { name: "Загрузка CSV" })).not.toBeInTheDocument();
});

it("keeps the current question when a mobile import is cancelled", async () => {
  setup();
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
  render(<App />);
  await select("A");
  fireEvent.change(screen.getByRole("textbox", { name: "Ваш вопрос" }), { target: { value: "Важный черновик" } });
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  expect(screen.getByRole("dialog", { name: "Загрузка CSV" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Закрыть загрузку CSV" }));
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toHaveValue("Важный черновик");
  expect(screen.getByRole("button", { name: "Источник A" })).toHaveAttribute("aria-pressed", "true");
});

it("can return from mobile import and open an existing source", async () => {
  setup();
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
  render(<App />);
  await screen.findByRole("button", { name: "Источник A" });
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  fireEvent.click(screen.getByRole("button", { name: "Закрыть загрузку CSV" }));
  fireEvent.click(screen.getByRole("button", { name: "Источник A" }));
  expect(screen.queryByRole("dialog", { name: "Новый анализ" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Рабочее пространство" })).toHaveAttribute("aria-pressed", "true");
});

it("opens mobile settings and applies a selected theme", async () => {
  setup();
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Чат" }));
  fireEvent.click(within(screen.getByRole("navigation", { name: "Мобильная навигация" })).getByRole("button", { name: "Настройки" }));
  expect(screen.getByRole("dialog", { name: "Настройки" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Закрыть настройки" })).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Тёмная тема" }));
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-theme", "dark");
  fireEvent.click(screen.getByRole("button", { name: "Закрыть настройки" }));
  expect(screen.queryByRole("dialog", { name: "Настройки" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть настройки" }));
  fireEvent.click(screen.getByTestId("settings-backdrop"));
  expect(screen.queryByRole("dialog", { name: "Настройки" })).not.toBeInTheDocument();
});

it("system theme follows a dark device preference", async () => {
  setup();
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("prefers-color-scheme"), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть настройки" }));
  fireEvent.click(screen.getByRole("button", { name: "Системная тема" }));
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-theme", "dark");
});

it("shows the attached source in mobile chat and can remove it", async () => {
  setup();
  render(<App />);
  await select("A");
  fireEvent.click(screen.getByRole("button", { name: "Чат" }));
  expect(screen.getByLabelText("Прикреплённый источник")).toHaveTextContent("Источник A");
  fireEvent.click(screen.getByRole("button", { name: "Убрать источник из чата" }));
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeDisabled();
});
it("explains the safe Railway setup instead of asking for a database password", async () => {
  setup();
  render(<App />);

  const postgresButton = await screen.findByRole("button", { name: "Подключить PostgreSQL" });
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => url === "/sources/postgresql/status"),
  ).toHaveLength(0);

  fireEvent.click(postgresButton);

  expect(await screen.findByRole("heading", { name: "Подключите PostgreSQL" })).toBeInTheDocument();
  expect(screen.getByText("POSTGRES_DSN")).toBeInTheDocument();
  expect(screen.queryByLabelText(/пароль/i)).not.toBeInTheDocument();
});

it("lets the user select an available PostgreSQL table after a successful check", async () => {
  const postgres = {
    ...source("postgresql:public:orders"),
    name: "public.orders",
    source_type: "postgresql",
  };
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([postgres]));
    if (url === "/sources/postgresql/status") return Promise.resolve(Response.json({ configured: true, connected: true }));
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([]));
    if (url.endsWith("/schema")) return Promise.resolve(Response.json(schema("postgresql:public:orders")));
    if (url.includes("/preview")) return Promise.resolve(Response.json([{ product: "Заказ" }]));
    if (url.endsWith("/profile")) return Promise.resolve(Response.json(profile));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Подключить PostgreSQL" }));
  expect(await screen.findByRole("heading", { name: "PostgreSQL подключён" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Выбрать public.orders" }));

  expect(await screen.findByRole("heading", { name: "public.orders" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeEnabled();
});

it("rechecks PostgreSQL after a temporary connection failure", async () => {
  const postgres = {
    ...source("postgresql:public:orders"),
    name: "public.orders",
    source_type: "postgresql",
  };
  let attempts = 0;
  const fetcher = vi.fn((url: string) => {
    if (url === "/health") return Promise.resolve(Response.json({ status: "ok", llm_provider: "mock" }));
    if (url === "/sources") return Promise.resolve(Response.json([postgres]));
    if (url === "/sources/postgresql/status") {
      attempts += 1;
      return Promise.resolve(Response.json({ configured: true, connected: attempts > 1 }));
    }
    if (url === "/chats?limit=100") return Promise.resolve(Response.json([]));
    return Promise.reject(new Error("Unexpected route " + url));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);

  fireEvent.click(await screen.findByRole("button", { name: "Подключить PostgreSQL" }));
  expect(await screen.findByRole("heading", { name: "PostgreSQL пока недоступен" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Повторить проверку" }));

  expect(await screen.findByRole("heading", { name: "PostgreSQL подключён" })).toBeInTheDocument();
});

it("does not switch back to an older conversation when its answer arrives late", async () => {
  const finish: ((response: Response) => void)[] = [];
  setup(() => new Promise((resolve) => finish.push(resolve)));
  render(<App />);
  await select("A");
  await ask("Старый");
  fireEvent.click(screen.getByRole("button", { name: "Добавить источник" }));
  await select("A");
  await ask("Новый");
  await act(async () => finish[0](Response.json({ answer: "Старый ответ", steps: 1, tool_results: [] })));
  expect(screen.queryByText("Старый ответ")).not.toBeInTheDocument();
  await act(async () => finish[1](Response.json({ answer: "Новый ответ", steps: 1, tool_results: [] })));
  expect(screen.getByText("Новый ответ")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Старый" }));
  expect(within(screen.getByRole("complementary", { name: "Чат с EVIA" })).getByText("Старый ответ")).toBeInTheDocument();
});
it("does not show implementation-status controls in the workspace header", async () => {
  setup();
  render(<App />);
  await screen.findByRole("button", { name: "Источник A" });
  expect(screen.queryByText(/Тестовая модель/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Тихий режим" })).not.toBeInTheDocument();
  expect(localStorage.getItem("linza.quiet")).toBeNull();
});
it("uploads a CSV, selects the returned source and loads its real preview", async () => {
  const uploads = mockCsvUpload(source("uploaded"));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/health")
      return Response.json({ status: "ok", llm_provider: "mock" });
    if (url === "/sources") return Response.json([]);
    if (url.endsWith("/schema")) return Response.json(schema("uploaded"));
    if (url.includes("/preview"))
      return Response.json([{ product: "uploaded-value" }]);
    if (url.endsWith("/profile")) return Response.json(profile);
    throw new Error("Unexpected route " + url);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByText("Нет источников");
  fireEvent.change(screen.getByLabelText("Загрузить CSV"), {
    target: {
      files: [
        new File(["product\nuploaded-value"], "example.csv", {
          type: "text/csv",
        }),
      ],
    },
  });
  expect(await screen.findByRole("heading", { name: "Источник uploaded" })).toBeInTheDocument();
  expect(uploads).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: /^Данные$/ }));
  expect(await screen.findByText("uploaded-value")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Источник uploaded" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", { name: "Ваш вопрос" })).toBeEnabled();
});
it("rejects an empty CSV before sending it to the server", async () => {
  setup();
  render(<App />);
  await screen.findByRole("button", { name: "Источник A" });
  fireEvent.change(screen.getByLabelText("Загрузить CSV"), {
    target: { files: [new File([], "empty.csv")] },
  });
  expect(
    await screen.findByText("Файл пуст. Выберите CSV с заголовком и данными."),
  ).toBeInTheDocument();
  expect(
    vi.mocked(fetch).mock.calls.some(([url]) => url === "/sources/csv"),
  ).toBe(false);
});
it("recovers source metadata after a failed preview request", async () => {
  let attempts = 0;
  setup(undefined, async () =>
    ++attempts === 1
      ? new Response("error", { status: 500 })
      : Response.json([{ product: "recovered" }]),
  );
  render(<App />);
  await select("A");
  fireEvent.click(
    await screen.findByRole("button", { name: "Повторить загрузку" }),
  );
  fireEvent.click(screen.getByRole("button", { name: /^Данные$/ }));
  expect(await screen.findByText("recovered")).toBeInTheDocument();
});
it("keeps a failed question in history after stopping the network request", async () => {
  setup(
    (init) =>
      new Promise((_, reject) =>
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        ),
      ),
  );
  render(<App />);
  await select("A");
  await ask("Останови этот вопрос");
  fireEvent.click(screen.getByRole("button", { name: "Прекратить ожидание" }));
  expect(
    await screen.findByText(
      "Ожидание остановлено. Сервер может продолжать обработку.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Останови этот вопрос" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Повторить вопрос" }),
  ).toBeEnabled();
});
it("shows thinking, cancellation, retry and the finished answer as real mascot states", async () => {
  let finish!: (r: Response) => void;
  let attempt = 0;
  setup((init) =>
    ++attempt === 1
      ? new Promise((_, reject) =>
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        )
      : new Promise((resolve) => {
          finish = resolve;
        }),
  );
  const { container } = render(<App />);
  await select("A");
  await ask("Проверь данные");
  expect(
    container.querySelector('[data-evia-state="thinking"]'),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Прекратить ожидание" }));
  await waitFor(() =>
    expect(
      container.querySelector('[data-evia-state="cancelled"]'),
    ).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Повторить вопрос" }));
  expect(
    container.querySelector('[data-evia-state="retrying"]'),
  ).toBeInTheDocument();
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  await act(async () =>
    finish(Response.json({ answer: "Готово", steps: 1, tool_results: [] })),
  );
  expect(
    container.querySelector('[data-evia-state="explaining"]'),
  ).toBeInTheDocument();
});
it("shows CSV upload state until the actual response and then uploaded state", async () => {
  setup();
  const uploads = mockCsvUpload(source("C"), false);
  const { container } = render(<App />);
  await select("A");
  fireEvent.change(screen.getByLabelText("Загрузить CSV"), {
    target: { files: [new File(["id\n1"], "new.csv")] },
  });
  expect(
    container.querySelector('[data-evia-state="uploading"]'),
  ).toBeInTheDocument();
  expect(uploads).toHaveLength(1);
  await act(async () => uploads[0].respond());
  expect(
    container.querySelector('[data-evia-state="uploaded"]'),
  ).toBeInTheDocument();
});
