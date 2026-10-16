import type { Answer } from "../../api";

import type { EviaState } from "../mascot/states";

export type Entry = {
  id: string;
  question: string;
  state: "pending" | "success" | "error";
  answer?: Answer;
  error?: string;
  mascotState?: EviaState;
};
export type View = "preview" | "schema" | "profile" | "results";
