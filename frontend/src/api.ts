import { z } from "zod";

const sourceSchema = z.object({
  source_id: z.string().min(1),
  name: z.string(),
  source_type: z.string(),
  status: z.string(),
  created_at: z.string(),
  schema_version: z.number().int(),
});
const schemaSchema = z.object({
  source_id: z.string(),
  version: z.number().int(),
  objects: z.array(
    z.object({
      object_id: z.string(),
      name: z.string(),
      object_type: z.string(),
      row_count: z.number().int().nonnegative().nullable(),
      fields: z.array(
        z.object({
          name: z.string(),
          inferred_type: z.string(),
          nullable: z.boolean().nullable(),
          is_identifier_candidate: z.boolean(),
          description: z.string().nullable().optional(),
        }),
      ),
    }),
  ),
});
const profileSchema = z.object({
  sample_size: z.number().int().nonnegative(),
  sample_limit: z.number().int().nonnegative(),
  note: z.string(),
  columns: z.record(
    z.string(),
    z.object({
      sample_non_null_count: z.number().int().nonnegative(),
      sample_null_count: z.number().int().nonnegative(),
      distinct_sample_values: z.number().int().nonnegative(),
      top_values: z.array(
        z.object({ value: z.string(), count: z.number().int().nonnegative() }),
      ),
    }),
  ),
});
const answerSchema = z.object({
  answer: z.string(),
  request_id: z.string().optional(),
  status: z.enum(["answered", "clarification", "error"]).optional(),
  answer_kind: z.enum(["demo", "model", "computed"]).optional(),
  analysis: z.object({ intent: z.string(), sql: z.string().nullable(), explanation: z.string() }).nullable().optional(),
  chat_id: z.string().nullable().optional(),
  steps: z.number().int().nonnegative(),
  timing: z.object({
    elapsed_ms: z.number().nonnegative(),
    llm_ms: z.number().nonnegative(),
    tools_ms: z.number().nonnegative(),
    calls: z.array(z.object({
      elapsed_ms: z.number().nonnegative(),
      model: z.string().nullable().optional(),
      load_ms: z.number().nonnegative().nullable().optional(),
      prompt_ms: z.number().nonnegative().nullable().optional(),
      generation_ms: z.number().nonnegative().nullable().optional(),
      prompt_tokens: z.number().int().nonnegative().nullable().optional(),
      generated_tokens: z.number().int().nonnegative().nullable().optional(),
    })),
  }).nullable().optional(),
  tool_results: z.array(
    z.object({
      tool_name: z.string(),
      ok: z.boolean(),
      data: z.unknown(),
      error: z.string().nullable().optional(),
    }),
  ),
});
const healthSchema = z.object({ status: z.string(), llm_provider: z.string() });
const postgresStatusSchema = z.object({
  configured: z.boolean(),
  connected: z.boolean(),
});
const rowsSchema = z.array(z.record(z.string(), z.unknown()));
const chatSummarySchema = z.object({
  chat_id: z.string().min(1),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
const chatMessageSchema = z.object({
  message_id: z.string().min(1),
  role: z.enum(["user", "assistant", "system", "tool"]),
  content: z.string(),
  created_at: z.string(),
});
const chatHistorySchema = z.object({
  chat_id: z.string().min(1),
  title: z.string(),
  messages: z.array(chatMessageSchema),
  total_messages: z.number().int().nonnegative(),
  next_offset: z.number().int().nonnegative().nullable(),
  next_before: z.number().int().nonnegative().nullable(),
  has_more: z.boolean(),
});
export type Source = z.infer<typeof sourceSchema>;
export type SourceSchema = z.infer<typeof schemaSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type Answer = z.infer<typeof answerSchema>;
export type Health = z.infer<typeof healthSchema>;
export type PostgresStatus = z.infer<typeof postgresStatusSchema>;
export type ChatSummary = z.infer<typeof chatSummarySchema>;
export type ChatHistory = z.infer<typeof chatHistorySchema>;
export type ChatMessage = z.infer<typeof chatMessageSchema>;
export type ToolResult = Answer["tool_results"][number];
export type Row = Record<string, unknown>;

// Keep chat creation alive to retain its ID, but stop the user's wait promptly.
export function waitForChat(chat: Promise<string>, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    if (signal.aborted) { abort(); return; }
    signal.addEventListener("abort", abort, { once: true });
    chat.then(
      (id) => { signal.removeEventListener("abort", abort); resolve(id); },
      (error) => { signal.removeEventListener("abort", abort); reject(error); },
    );
  });
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const knownErrors: Record<string, string> = {
  "CSV contains duplicate column names": "Названия столбцов повторяются. Укажите уникальные заголовки.",
  "CSV must contain non-empty column names": "Каждый столбец должен иметь непустое название.",
  "Only CSV files are supported": "Поддерживаются только файлы .csv.",
  "Uploaded CSV is empty": "Файл пуст. Выберите CSV с заголовком и данными.",
  "CSV must be valid UTF-8":
    "Сохраните CSV в кодировке UTF-8 и загрузите снова.",
  "CSV must contain a header row":
    "Первая строка CSV должна содержать названия столбцов.",
};
async function request<T>(
  path: string,
  validator: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init.headers },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      "Нет связи с сервером. Проверьте, запущен ли сервис, и повторите запрос.",
      0,
    );
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      body && typeof body === "object" && "detail" in body ? body.detail : null;
    if (typeof detail === "string" && knownErrors[detail])
      throw new ApiError(knownErrors[detail], response.status);
    const errors: Record<number, string> = {
      400: "Не удалось прочитать данные. Проверьте формат файла и повторите запрос.",
      404: "Источник больше не доступен. Обновите список источников.",
      413: "Файл слишком большой для сервера. Попробуйте меньший CSV.",
      422: "Проверьте данные запроса: вопрос должен содержать от 1 до 4000 символов.",
      502: "Не удалось получить ответ модели. Проверьте подключение к модели и повторите вопрос.",
      503: "Сервис временно недоступен. Повторите запрос немного позже.",
    };
    throw new ApiError(
      errors[response.status] ||
        `Сервер не смог выполнить запрос (HTTP ${response.status}). Повторите попытку.`,
      response.status,
    );
  }
  const body: unknown = await response.json().catch(() => {
    throw new Error("Сервер вернул неподдерживаемый формат ответа.");
  });
  const result = validator.safeParse(body);
  if (!result.success)
    throw new Error(
      "Сервер вернул неподдерживаемый формат данных. Обновите страницу или проверьте версию сервиса.",
    );
  return result.data;
}
const path = (id: string) => `/sources/${encodeURIComponent(id)}`;
export const api = {
  createChat: (title: string) => request("/chats", chatSummarySchema, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  }),
  chats: (signal?: AbortSignal) => request("/chats?limit=100", z.array(chatSummarySchema), { signal }),
  chatHistory: (chatId: string, before?: number, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: "50" });
    if (before !== undefined) query.set("before", String(before));
    return request(`/chats/${encodeURIComponent(chatId)}?${query}`, chatHistorySchema, { signal });
  },
  chat: async (question: string, id: string, chatId: string, signal?: AbortSignal) => {
    const result = await request(`/agent/chat?chat_id=${encodeURIComponent(chatId)}`, answerSchema, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, source_ids: [id] }), signal,
    });
    if (result.chat_id !== chatId) throw new Error("Сервер вернул ответ другого диалога. Повторите запрос.");
    return result;
  },
  health: (signal?: AbortSignal) =>
    request("/health", healthSchema, { signal }),
  sources: (signal?: AbortSignal) =>
    request("/sources", z.array(sourceSchema), { signal }),
  postgresStatus: (signal?: AbortSignal) =>
    request("/sources/postgresql/status", postgresStatusSchema, { signal }),
  schema: async (id: string, signal?: AbortSignal) => {
    const schema = await request(`${path(id)}/schema`, schemaSchema, {
      signal,
    });
    if (schema.source_id !== id)
      throw new Error(
        "Сервер вернул схему другого источника. Обновите данные.",
      );
    return schema;
  },
  preview: (id: string, signal?: AbortSignal) =>
    request(`${path(id)}/preview?limit=100`, rowsSchema, { signal }),
  profile: (id: string, signal?: AbortSignal) =>
    request(`${path(id)}/profile`, profileSchema, { signal }),
  upload: (file: File, signal?: AbortSignal) => {
    const body = new FormData();
    body.append("file", file);
    return request("/sources/csv", sourceSchema, {
      method: "POST",
      body,
      signal,
    });
  },
  ask: (question: string, id: string, signal?: AbortSignal) =>
    request("/agent/ask", answerSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, source_ids: [id] }),
      signal,
    }),
};
export const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Не удалось выполнить запрос. Попробуйте ещё раз.";
