import { api } from "./api";
const source = {
  source_id: "a",
  name: "A",
  source_type: "csv",
  status: "available",
  created_at: "2026-10-16",
  schema_version: 1,
};
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
it("maps provider failure to an actionable message", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("upstream failure", { status: 502 })),
  );
  await expect(api.ask("Покажи данные", "a")).rejects.toThrow("модели");
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
