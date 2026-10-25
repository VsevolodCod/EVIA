import type { Answer } from "../../api";

import type { EviaState } from "../mascot/states";

export type Entry = {
  id: string;
  question: string;
  state: "pending" | "success" | "error";
  answer?: Answer;
  error?: string;
  mascotState?: EviaState;
  historyDetail?: "legacy" | "unsupported" | "invalid";
  startedAt?: number;
  elapsedMs?: number;
  conversationId?: string;
};
export type View =
  | "overview"
  | "preview"
  | "schema"
  | "profile"
  | "quality"
  | "results";
