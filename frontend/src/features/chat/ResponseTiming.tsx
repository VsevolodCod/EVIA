import { useEffect, useState } from "react";
import type { Entry } from "./types";
import { useLanguage } from "../../i18n";

const seconds = (ms: number) => `${(ms / 1000).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} с`;

export function ResponseTiming({ entry }: { entry: Entry }) {
  const { t, locale } = useLanguage();
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
  const seconds = (ms: number) => `${(ms / 1000).toLocaleString(locale === "en" ? "en-US" : "ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ${t("с")}`;
  return <div className="response-timing" aria-live="off">
    <p>{entry.state === "success" ? t("Ответ за") : t("Ожидание")} {seconds(elapsed)}</p>
    {timing && <details>
      <summary>{t("Подробности времени")}</summary>
      <p>{t("На сервере:")} {seconds(timing.elapsed_ms)}. {t("Вызовы модели:")} {seconds(timing.llm_ms)}. {t("Инструменты:")} {seconds(timing.tools_ms)}.</p>
      <ol>{timing.calls.map((call, index) => <li key={index}>
        {t("Вызов")} {index + 1}{call.model ? ` (${call.model})` : ""}: {seconds(call.elapsed_ms)}.
        {call.provider_total_ms != null && <> {t("По таймеру провайдера:")} {seconds(call.provider_total_ms)}.</>}
        {call.load_ms != null && <> {t("Загрузка модели:")} {seconds(call.load_ms)}.</>}
        {call.prompt_ms != null && <> {t("Обработка входа:")} {seconds(call.prompt_ms)}.</>}
        {call.generation_ms != null && <> {t("Генерация:")} {seconds(call.generation_ms)}.</>}
        {call.generated_tokens != null && call.generation_ms != null && call.generation_ms > 0 &&
          <> {t("Скорость:")} {(call.generated_tokens * 1000 / call.generation_ms).toLocaleString(locale === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 1 })} {t("токенов/с")}.</>}
      </li>)}</ol>
      <p>{t("Общее время включает сеть и обработку ответа. Вызовы модели включают ожидание Ollama; это не время до первого токена.")}</p>
    </details>}
  </div>;
}
