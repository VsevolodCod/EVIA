import { storedAnalysis, type ChatMessage } from "../../api";
import type { Entry } from "./types";

export const CHAT_SOURCE_STORAGE_KEY = "evia.chat-sources.v1";

export function savedChatSources(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(CHAT_SOURCE_STORAGE_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] =>
        typeof entry[0] === "string" && typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

export function entriesFromMessages(chatId: string, messages: ChatMessage[]): Entry[] {
  const entries: Entry[] = [];
  let user: ChatMessage | undefined;
  for (const [index, message] of messages.entries()) {
    if (message.role === "user") {
      // The agent stores this internal continuation prompt in its trace. It is
      // not a new question from the person who owns the chat.
      if (user && message.content === "Продолжи ответ точно с места обрыва, без повторения уже написанного.") continue;
      user = message;
      continue;
    }
    if (message.role === "assistant" && user) {
      const restored = storedAnalysis(message);
      // Tool calls and partial model output precede the saved final answer.
      // Neither is a standalone response to the user's question.
      if (restored.kind !== "restored" && (
        message.tool_calls?.length || !message.content.trim() ||
        (messages[index + 1]?.role === "user" &&
          messages[index + 1]?.content === "Продолжи ответ точно с места обрыва, без повторения уже написанного.")
      )) continue;
      entries.push({
        id: user.message_id,
        conversationId: chatId,
        question: user.content,
        state: "success",
        answer: restored.kind === "restored"
          ? restored.answer
          : { answer: message.content, steps: 0, tool_results: [] },
        historyDetail: restored.kind === "restored" ? undefined : restored.kind,
        elapsedMs: restored.kind === "restored"
          ? restored.answer.timing?.elapsed_ms
          : undefined,
      });
      user = undefined;
    }
  }
  if (user) {
    entries.push({
      id: user.message_id,
      conversationId: chatId,
      question: user.content,
      state: "error",
      mascotState: "warning",
      error: "Ответ для этого вопроса не сохранился. Повторите запрос.",
    });
  }
  return entries;
}

export function mergeEntries(existing: Entry[], loaded: Entry[]): Entry[] {
  const known = new Set(existing.map((entry) => entry.id));
  return [...loaded.filter((entry) => !known.has(entry.id)), ...existing];
}
