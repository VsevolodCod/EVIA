import { render, screen } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { EviaMascot } from "../../components/EviaMascot";
import { EVIA_STATES } from "./states";
import { resolveEviaState } from "./resolveEviaState";

it("ships every state as a standalone safe local SVG", () => {
  expect(EVIA_STATES).toHaveLength(40);
  expect(new Set(EVIA_STATES.map((s) => s.id)).size).toBe(40);
  const directory = resolve(process.cwd(), "public/mascot");
  expect(
    readdirSync(directory)
      .filter((f) => f.endsWith(".svg"))
      .sort(),
  ).toEqual(EVIA_STATES.map((s) => `${s.id}.svg`).sort());
  for (const state of EVIA_STATES) {
    const svg = readFileSync(resolve(directory, `${state.id}.svg`), "utf8");
    expect(svg).toContain('viewBox="0 0 320 320"');
    expect(svg).not.toMatch(/<script|<foreignObject|\son\w+=|(?:href|src)=/i);
  }
});
it("uses Russian accessible names and can be decorative and quiet", () => {
  const { rerender, container } = render(
    <EviaMascot state="uploading" size={96} />,
  );
  expect(
    screen.getByRole("img", { name: "Эвия — Загрузка CSV" }),
  ).toHaveAttribute("src", "/mascot/uploading.svg");
  rerender(<EviaMascot state="success" decorative quiet />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(container.querySelector('[data-motion="off"]')).toBeInTheDocument();
});
it("reflects real events without invented progress and ignores another source upload", () => {
  expect(resolveEviaState({})).toBe("welcome");
  expect(resolveEviaState({ selectedId: "A" })).toBe("waiting");
  expect(resolveEviaState({ selectedId: "A", uploadedId: "B" })).toBe(
    "waiting",
  );
  expect(resolveEviaState({ selectedId: "A", uploadedId: "A" })).toBe(
    "uploaded",
  );
  expect(resolveEviaState({ draft: "Вопрос", selectedId: "A" })).toBe(
    "listening",
  );
  expect(resolveEviaState({ uploading: true, request: "thinking" })).toBe(
    "uploading",
  );
  expect(resolveEviaState({ request: "retrying" })).toBe("retrying");
  expect(
    resolveEviaState({
      entry: {
        id: "1",
        question: "?",
        state: "error",
        mascotState: "cancelled",
      },
    }),
  ).toBe("cancelled");
});
it("does not celebrate failed tools or infer no-data from absent tools", () => {
  const entry = {
    id: "1",
    question: "?",
    state: "success" as const,
    answer: { answer: "ok", steps: 1, tool_results: [] },
  };
  expect(resolveEviaState({ entry })).toBe("explaining");
  expect(
    resolveEviaState({
      entry: {
        ...entry,
        answer: {
          ...entry.answer,
          tool_results: [{ tool_name: "test", ok: false, data: null }],
        },
      },
    }),
  ).toBe("warning");
});
it("maps transport errors without guessing from LLM text", async () => {
  const { ApiError } = await import("../../api");
  const { errorEviaState } = await import("./resolveEviaState");
  expect(errorEviaState(new ApiError("offline", 0))).toBe("connection_lost");
  expect(errorEviaState(new ApiError("denied", 403))).toBe("permission_denied");
  expect(errorEviaState(new ApiError("timeout", 504))).toBe("timeout");
  expect(errorEviaState(new ApiError("bad CSV", 400), true)).toBe(
    "invalid_csv",
  );
  expect(errorEviaState(new Error("timeout"))).toBe("error");
});
