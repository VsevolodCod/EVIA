import { ApiError } from "../../api";
import type { Entry } from "../chat/types";
import type { EviaState } from "./states";

export function errorEviaState(error: unknown, upload = false): EviaState {
  if (error instanceof ApiError) {
    if (error.status === 0) return "connection_lost";
    if (error.status === 401 || error.status === 403)
      return "permission_denied";
    if (error.status === 408 || error.status === 504) return "timeout";
    if (upload && (error.status === 400 || error.status === 422))
      return "invalid_csv";
  }
  return "error";
}

export function resolveEviaState(context: {
  uploading?: boolean;
  uploadFailure?: EviaState | null;
  request?: EviaState;
  connectionFailure?: boolean;
  selectedId?: string | null;
  uploadedId?: string | null;
  draft?: string;
  entry?: Entry;
}): EviaState {
  if (context.uploading) return "uploading";
  if (context.request) return context.request;
  if (context.uploadFailure) return context.uploadFailure;
  if (context.entry?.state === "error")
    return context.entry.mascotState ?? "error";
  if (context.connectionFailure) return "connection_lost";
  if (context.draft?.trim()) return "listening";
  if (context.entry?.answer) {
    if (context.entry.answer.tool_results.some((result) => !result.ok))
      return "warning";
    return "explaining";
  }
  if (context.selectedId && context.uploadedId === context.selectedId)
    return "uploaded";
  return context.selectedId ? "waiting" : "welcome";
}

export function eviaStatus(state: EviaState, language: "ru" | "en" = "ru"): string {
  if (language === "en") {
    const english: Partial<Record<EviaState, string>> = {
      welcome: "Hello! Add a CSV to get started.", waiting: "Ready for your question.", listening: "Listening. Send your question when ready.", thinking: "Waiting for the agent's response.", retrying: "Retrying the request.", uploading: "Uploading CSV…", uploaded: "CSV uploaded. You can explore the data.", explaining: "The answer is ready. What next?", warning: "The answer arrived, but some tools failed.", cancelled: "Waiting stopped; the server may still be processing.", invalid_csv: "Check the CSV format and try again.", connection_lost: "Service connection lost. Try again.", permission_denied: "The service denied access to the request.", timeout: "The service reported a timeout.", error: "Could not complete the request. You can retry.",
    };
    return english[state] ?? "EVIA is here to help.";
  }
  const statuses: Partial<Record<EviaState, string>> = {
    welcome: "Привет! Добавьте CSV, и начнём.",
    waiting: "Готова к вашему вопросу.",
    listening: "Слушаю. Отправьте вопрос, когда будете готовы.",
    thinking: "Жду ответ агента на ваш вопрос.",
    retrying: "Повторяю запрос.",
    uploading: "Загружаю CSV…",
    uploaded: "CSV загружен. Можно исследовать данные.",
    explaining: "Ответ готов. Что исследуем дальше?",
    warning: "Ответ получен, но есть ошибки инструментов.",
    cancelled: "Ожидание прекращено; сервер может продолжать обработку.",
    invalid_csv: "Проверьте формат CSV и попробуйте ещё раз.",
    connection_lost: "Нет связи с сервисом. Попробуйте ещё раз.",
    permission_denied: "Сервис отклонил доступ к запросу.",
    timeout: "Сервис сообщил о превышении времени ожидания.",
    error: "Не удалось завершить запрос. Можно повторить.",
  };
  return statuses[state] ?? "EVIA рядом.";
}
