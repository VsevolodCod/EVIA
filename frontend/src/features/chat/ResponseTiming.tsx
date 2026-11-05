import { useEffect, useState } from "react";
import { useLanguage } from "../../language";
import type { Entry } from "./types";

const seconds = (ms: number) => `${(ms / 1000).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} с`;

export function ResponseTiming({ entry }: { entry: Entry }) {
  const { t, language } = useLanguage();
  const duration = (ms: number) => language === "ru" ? seconds(ms) : `${(ms / 1000).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
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
    <p>{entry.state === "success" ? t("Ответ за", "Answered in") : t("Ожидание", "Waiting")} {duration(elapsed)}</p>
    {timing && <details>
      <summary>{t("Подробности времени", "Timing details")}</summary>
      <p>{t("На сервере", "Server")}: {duration(timing.elapsed_ms)}. {t("Вызовы модели", "Model calls")}: {duration(timing.llm_ms)}. {t("Инструменты", "Tools")}: {duration(timing.tools_ms)}.</p>
      <ol>{timing.calls.map((call, index) => <li key={index}>
        {t("Вызов", "Call")} {index + 1}{call.model ? ` (${call.model})` : ""}: {duration(call.elapsed_ms)}.
        {call.provider_total_ms != null && <> {t("По таймеру провайдера", "Provider timing")}: {duration(call.provider_total_ms)}.</>}
        {call.load_ms != null && <> {t("Загрузка модели", "Model loading")}: {duration(call.load_ms)}.</>}
        {call.prompt_ms != null && <> {t("Обработка входа", "Input processing")}: {duration(call.prompt_ms)}.</>}
        {call.generation_ms != null && <> {t("Генерация", "Generation")}: {duration(call.generation_ms)}.</>}
        {call.generated_tokens != null && call.generation_ms != null && call.generation_ms > 0 &&
          <> {t("Скорость", "Speed")}: {(call.generated_tokens * 1000 / call.generation_ms).toLocaleString(language === "ru" ? "ru-RU" : "en-US", { maximumFractionDigits: 1 })} {t("токенов/с", "tokens/s")}.</>}
      </li>)}</ol>
      <p>{t("Общее время включает сеть и обработку ответа. Вызовы модели включают ожидание Ollama; это не время до первого токена.", "Total time includes network and response processing. Model calls include waiting for Ollama; this is not time to first token.")}</p>
    </details>}
  </div>;
}
