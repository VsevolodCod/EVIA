import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
      if (url === "/chats") return Promise.resolve(Response.json({ chat_id: `chat-${++nextChat}` }));
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
  fireEvent.click(screen.getByRole("button", { name: "Новый анализ" }));
  await ask("Другой диалог");
  await screen.findByText("Ответ: Другой диалог");
  expect(screen.queryByText("Ответ: Первый")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Первый" }));
  expect(screen.getByText("Ответ: Уточнение")).toBeInTheDocument();
  await ask("Продолжение");
  await screen.findByText("Ответ: Продолжение");
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

it("does not switch back to an older conversation when its answer arrives late", async () => {
  const finish: ((response: Response) => void)[] = [];
  setup(() => new Promise((resolve) => finish.push(resolve)));
  render(<App />);
  await select("A");
  await ask("Старый");
  fireEvent.click(screen.getByRole("button", { name: "Новый анализ" }));
  await ask("Новый");
  await act(async () => finish[0](Response.json({ answer: "Старый ответ", steps: 1, tool_results: [] })));
  expect(screen.queryByText("Старый ответ")).not.toBeInTheDocument();
  await act(async () => finish[1](Response.json({ answer: "Новый ответ", steps: 1, tool_results: [] })));
  expect(screen.getByText("Новый ответ")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Старый" }));
  expect(screen.getByText("Старый ответ")).toBeInTheDocument();
});
it("shows mock mode honestly and only persists the quiet setting", async () => {
  setup();
  render(<App />);
  expect(await screen.findByText(/Тестовая модель/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Тихий режим" }));
  expect(localStorage.getItem("linza.quiet")).toBe("true");
  expect(localStorage.length).toBe(1);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Тихий режим" })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
});
it("uploads a CSV, selects the returned source and loads its real preview", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/health")
      return Response.json({ status: "ok", llm_provider: "mock" });
    if (url === "/sources") return Response.json([]);
    if (url === "/sources/csv") {
      expect(init?.body).toBeInstanceOf(FormData);
      expect((init?.body as FormData).get("file")).toBeInstanceOf(File);
      return Response.json(source("uploaded"));
    }
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
  const base = vi.mocked(fetch).getMockImplementation()!;
  let finish!: (r: Response) => void;
  vi.mocked(fetch).mockImplementation((url, init) =>
    url === "/sources/csv"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : base(url, init),
  );
  const { container } = render(<App />);
  await select("A");
  fireEvent.change(screen.getByLabelText("Загрузить CSV"), {
    target: { files: [new File(["id\n1"], "new.csv")] },
  });
  expect(
    container.querySelector('[data-evia-state="uploading"]'),
  ).toBeInTheDocument();
  await act(async () => finish(Response.json(source("C"))));
  expect(
    container.querySelector('[data-evia-state="uploaded"]'),
  ).toBeInTheDocument();
});
