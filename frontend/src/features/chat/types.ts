import type { Answer } from "../../api";

export type Entry = {
  id: string;
  question: string;
  state: "pending" | "success" | "error";
  answer?: Answer;
  error?: string;
};
export type View = "preview" | "schema" | "profile" | "results";
