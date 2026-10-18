import { act, render, screen } from "@testing-library/react";
import { ResponseTiming } from "./ResponseTiming";

it("counts actual waiting, freezes after an error, and starts a retry from zero", () => {
  vi.useFakeTimers();
  let now = 1000;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  const entry = { id: "q", question: "test", state: "pending" as const, startedAt: 1000 };
  const { rerender, unmount } = render(<ResponseTiming entry={entry} />);
  try {
    expect(screen.getByText("Ожидание 0,0 с")).toBeInTheDocument();
    act(() => { now = 3500; vi.advanceTimersByTime(500); });
    expect(screen.getByText("Ожидание 2,5 с")).toBeInTheDocument();
    rerender(<ResponseTiming entry={{ ...entry, state: "error", elapsedMs: 2600 }} />);
    act(() => { now = 10000; vi.advanceTimersByTime(1000); });
    expect(screen.getByText("Ожидание 2,6 с")).toBeInTheDocument();
    rerender(<ResponseTiming key="retry" entry={{ ...entry, startedAt: now }} />);
    expect(screen.getByText("Ожидание 0,0 с")).toBeInTheDocument();
  } finally {
    unmount(); vi.restoreAllMocks(); vi.useRealTimers();
  }
});

it("separates browser duration from server metrics and hides unavailable metrics", () => {
  const entry = { id: "q", question: "test", state: "success" as const, elapsedMs: 12500 };
  const { rerender } = render(<ResponseTiming entry={entry} />);
  expect(screen.getByText("Ответ за 12,5 с")).toBeInTheDocument();
  expect(screen.queryByText("Подробности времени")).not.toBeInTheDocument();
  rerender(<ResponseTiming entry={{ ...entry, answer: { answer: "ok", steps: 1, tool_results: [], timing: {
    elapsed_ms: 12000, llm_ms: 11000, tools_ms: 500,
    calls: [{ elapsed_ms: 11000, load_ms: null, generation_ms: 1000, generated_tokens: 20 }],
  } } }} />);
  expect(screen.getByText(/На сервере: 12,0 с/)).toBeInTheDocument();
  expect(screen.getByText(/20 токенов\/с/)).toBeInTheDocument();
  expect(screen.queryByText(/Загрузка модели/)).not.toBeInTheDocument();
});
