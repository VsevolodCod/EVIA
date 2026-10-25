import { useEffect, useState } from "react";
import type { Entry } from "./types";

const seconds = (ms: number) => `${(ms / 1000).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} с`;

export function ResponseTiming({ entry }: { entry: Entry }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (entry.state !== "pending") return;
    const timer = window.setInterval(() => setNow(performance.now()), 500);
    return () => window.clearInterval(timer);
  }, [entry.state, entry.startedAt]);
  const elapsed = entry.state === "pending"
    ? entry.startedAt === undefined ? undefined : Math.max(0, now - entry.startedAt)
    : entry.elapsedMs;
  if (elapsed === undefined) return null;
  const timing = entry.answer?.timing;
  return <div className="response-timing" aria-live="off">
    <p>{entry.state === "success" ? "Ответ за" : "Ожидание"} {seconds(elapsed)}</p>
    {timing && <details>
      <summary>Подробности времени</summary>
      <p>На сервере: {seconds(timing.elapsed_ms)}. Вызовы модели: {seconds(timing.llm_ms)}. Инструменты: {seconds(timing.tools_ms)}.</p>
      <ol>{timing.calls.map((call, index) => <li key={index}>
        Вызов {index + 1}{call.model ? ` (${call.model})` : ""}: {seconds(call.elapsed_ms)}.
        {call.provider_total_ms != null && <> По таймеру провайдера: {seconds(call.provider_total_ms)}.</>}
        {call.load_ms != null && <> Загрузка модели: {seconds(call.load_ms)}.</>}
        {call.prompt_ms != null && <> Обработка входа: {seconds(call.prompt_ms)}.</>}
        {call.generation_ms != null && <> Генерация: {seconds(call.generation_ms)}.</>}
        {call.generated_tokens != null && call.generation_ms != null && call.generation_ms > 0 &&
          <> Скорость: {(call.generated_tokens * 1000 / call.generation_ms).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} токенов/с.</>}
      </li>)}</ol>
      <p>Общее время включает сеть и обработку ответа. Вызовы модели включают ожидание Ollama; это не время до первого токена.</p>
    </details>}
  </div>;
}
