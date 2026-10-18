import type { Entry } from "../chat/types";
import { SafeMarkdown } from "../chat/SafeMarkdown";
import { ToolResults } from "./ToolResults";
import { EviaMascot } from "../../components/EviaMascot";

export function AnalysisResult({ entry }: { entry?: Entry }) {
  return (
    <div className="analytics-section analysis-result">
      <div className="analytics-title">
        <div>
          <span className="analytics-kicker">ОТ ВОПРОСА К ВЫВОДУ</span>
          <h2>Результат анализа</h2>
        </div>
      </div>
      {entry?.answer ? (
        <>
          <p className="analysis-question">{entry.question}</p>
          <section className="analysis-answer" aria-label="Вывод EVIA">
            <span className="answer-signature">EVIA</span>
            <SafeMarkdown>
              {entry.answer.answer || "Модель вернула пустой ответ."}
            </SafeMarkdown>
          </section>
          {entry.answer.tool_results.length > 0 && (
            <ToolResults results={entry.answer.tool_results} />
          )}
        </>
      ) : (
        <div className="analytics-empty">
          <EviaMascot
            state={
              entry?.state === "pending"
                ? "analyzing"
                : entry?.state === "error"
                  ? "error"
                  : "waiting"
            }
            size={100}
            decorative
          />
          <h3>
            {entry?.state === "pending"
              ? "EVIA изучает ваш вопрос"
              : entry?.state === "error"
                ? "Не удалось получить результат"
                : "Начните с вопроса"}
          </h3>
          <p>
            {entry?.state === "error"
              ? "Повторите вопрос в диалоге справа."
              : "Здесь появятся выводы и результаты вычислений из вашего диалога."}
          </p>
        </div>
      )}
    </div>
  );
}
