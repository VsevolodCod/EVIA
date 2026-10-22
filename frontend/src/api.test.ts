import { api, waitForChat } from "./api";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
const source = {
  source_id: "a",
  name: "A",
  source_type: "csv",
  status: "available",
  created_at: "2026-10-16",
  schema_version: 1,
};

it("continues the requested chat and rejects a response from another chat", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ answer: "ok", chat_id: "chat-A", steps: 1, tool_results: [] }))
    .mockResolvedValueOnce(Response.json({ answer: "wrong", chat_id: "chat-B", steps: 1, tool_results: [] }));
  vi.stubGlobal("fetch", fetcher);
  expect((await api.chat("next", "source-A", "chat-A")).answer).toBe("ok");
  expect(fetcher).toHaveBeenCalledWith("/agent/chat?chat_id=chat-A", expect.objectContaining({
    body: JSON.stringify({ question: "next", source_ids: ["source-A"] }),
  }));
  await expect(api.chat("next", "source-A", "chat-A")).rejects.toThrow("другого диалога");
});

it("cancels waiting for creation without losing the reusable chat ID", async () => {
  let finish!: (id: string) => void;
  const chat = new Promise<string>((resolve) => { finish = resolve; });
  const controller = new AbortController();
  const pending = waitForChat(chat, controller.signal);
  controller.abort();
  await expect(pending).rejects.toThrow("Aborted");
  finish("created-chat");
  await expect(waitForChat(chat, new AbortController().signal)).resolves.toBe("created-chat");
});

it("accepts shared versioned fixtures without breaking the current API reader", async () => {
  const fixture = (name: string) => JSON.parse(readFileSync(resolve(process.cwd(), `../contracts/v1/fixtures/${name}.json`), "utf8")).data;
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(Response.json([fixture("source")]))
    .mockResolvedValueOnce(Response.json(fixture("profile")))
    .mockResolvedValueOnce(Response.json(fixture("success"))));
  expect((await api.sources())[0].source_id).toBe("synthetic-sales");
  expect((await api.profile("synthetic-sales")).sample_size).toBe(2);
  expect((await api.ask("fixture", "synthetic-sales")).tool_results[0].data).toEqual([{ id: "0001" }]);
});

it("retains exact full-snapshot statistics while labeling top values as sample data", async () => {
  const profile = {
    sample_size: 5,
    sample_limit: 500,
    processed_rows: 12,
    coverage: "full",
    snapshot_id: "snapshot-001",
    note: "Top values use a bounded sample.",
    columns: {
      amount: {
        sample_non_null_count: 5,
        sample_null_count: 0,
        distinct_sample_values: 4,
        top_values: [{ value: "12.50", count: 2 }],
        top_values_coverage: "sample",
        non_null_count: 10,
        null_count: 2,
        empty_count: 1,
        distinct_count: 8,
        uniqueness_ratio: 0.8,
        is_identifier_candidate: false,
        numeric: {
          count: 10,
          minimum: "0.01",
          maximum: "100.50",
          total: "457.75",
          average: "45.775",
        },
      },
      created_at: {
        sample_non_null_count: 5,
        sample_null_count: 0,
        distinct_sample_values: 5,
        top_values: [],
        top_values_coverage: "sample",
        non_null_count: 12,
        null_count: 0,
        empty_count: 0,
        distinct_count: 12,
        uniqueness_ratio: 1,
        is_identifier_candidate: true,
        temporal: {
          count: 12,
          minimum: "2026-01-01T00:00:00Z",
          maximum: "2026-01-12T00:00:00Z",
        },
      },
    },
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(profile)));

  await expect(api.profile("snapshot-source")).resolves.toEqual(profile);
});

it("accepts valid source responses and rejects an invalid response shape", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(Response.json([source]))
      .mockResolvedValueOnce(Response.json([{ source_id: 17 }])),
  );
  expect(await api.sources()).toEqual([source]);
  await expect(api.sources()).rejects.toThrow("формат");
});
it("reads only the safe PostgreSQL connection status", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    Response.json({ configured: true, connected: true }),
  );
  vi.stubGlobal("fetch", fetcher);

  await expect(api.postgresStatus()).resolves.toEqual({
    configured: true,
    connected: true,
  });
  expect(fetcher).toHaveBeenCalledWith(
    "/sources/postgresql/status",
    expect.any(Object),
  );
});
it("maps provider failure to an actionable message", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("upstream failure", { status: 502 })),
  );
  await expect(api.ask("Покажи данные", "a")).rejects.toThrow("модели");
});
it("shows CSV row accounting from a structured import error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
    detail: {
      message: "CSV row ending at line 3 has 3 fields; expected 2",
      report: { rows_read: 2, accepted_rows: 1, rejected_rows: 1, errors: ["CSV row ending at line 3 has 3 fields; expected 2"] },
    },
  }, { status: 400 })));
  await expect(api.upload(new File(["a,b\n1,2\n3,4,5"], "bad.csv")))
    .rejects.toThrow("Принято 1 из 2 строк, отклонено 1");
});
it("marks a repeat CSV upload with its existing source ID", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json(source));
  vi.stubGlobal("fetch", fetcher);
  await api.upload(new File(["id\n1\n"], "new.csv"), undefined, "existing-id");
  const request = fetcher.mock.calls[0][1];
  expect(request.body.get("source_id")).toBe("existing-id");
});
it("sends only selected source and question, without prior conversational history", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      Response.json({ answer: "Ответ", steps: 1, tool_results: [] }),
    );
  vi.stubGlobal("fetch", fetcher);
  await api.ask("Покажи данные", "a");
  expect(fetcher).toHaveBeenCalledWith(
    "/agent/ask",
    expect.objectContaining({
      body: JSON.stringify({ question: "Покажи данные", source_ids: ["a"] }),
    }),
  );
});
