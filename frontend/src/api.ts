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
  steps: z.number().int().nonnegative(),
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
const rowsSchema = z.array(z.record(z.string(), z.unknown()));
export type Source = z.infer<typeof sourceSchema>;
export type SourceSchema = z.infer<typeof schemaSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type Answer = z.infer<typeof answerSchema>;
export type Health = z.infer<typeof healthSchema>;
export type ToolResult = Answer["tool_results"][number];
export type Row = Record<string, unknown>;

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
  health: (signal?: AbortSignal) =>
    request("/health", healthSchema, { signal }),
  sources: (signal?: AbortSignal) =>
    request("/sources", z.array(sourceSchema), { signal }),
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
