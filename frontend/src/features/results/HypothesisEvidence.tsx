import { useLanguage } from "../../language";
type Value = Record<string, unknown>;

function object(value: unknown): value is Value {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isHypothesisEvidence(value: unknown): value is Value & { results: unknown[] } {
  return object(value) && Array.isArray(value.results);
}

function label(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function number(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(value);
}

function signed(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${number(value)}`;
}

function probability(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value > 0 && value < 0.001 ? "<0,001" : number(value);
}

export function HypothesisEvidence({ evidence }: { evidence: Value & { results: unknown[] } }) {
  const { t } = useLanguage();
  return <div className="hypothesis-evidence" aria-label={t("Проверка гипотезы", "Hypothesis test")}>
    <h4>{label(evidence.statement, t("Проверка гипотезы", "Hypothesis test"))}</h4>
    {evidence.results.map((item, index) => {
      if (!object(item)) return null;
      const data = object(item.data) ? item.data : {};
      if (item.status !== "completed") return <p className="error-text" key={index}>
        {t("Проверка не выполнена.", "The test failed.")} {label(item.error, t("Уточните поля и повторите запрос.", "Check the fields and retry."))}
      </p>;
      if (item.method === "compare") {
        const left = object(data.left) ? data.left : {};
        const right = object(data.right) ? data.right : {};
        const uncertainty = object(data.uncertainty) ? data.uncertainty : null;
        const differenceInterval = uncertainty && object(uncertainty.confidence_interval)
          ? uncertainty.confidence_interval : null;
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>{label(left.label, t("Группа 1", "Group 1"))}</span><strong>{number(left.value)}</strong></div>
            <div><span>{label(right.label, t("Группа 2", "Group 2"))}</span><strong>{number(right.value)}</strong></div>
            <div><span>{t("Разница", "Difference")} ({label(right.label, t("Группа 2", "Group 2"))} − {label(left.label, t("Группа 1", "Group 1"))})</span><strong>{signed(data.delta)}</strong></div>
          </div>
          {typeof data.change_percent === "number" && <p>{t("Изменение", "Change")}: {signed(data.change_percent)}%</p>}
          {differenceInterval && <p>{t("Доверительный интервал разницы", "Confidence interval for the difference")}: {number(differenceInterval.low)} — {number(differenceInterval.high)}</p>}
          {uncertainty?.status === "estimated" && <p>p-value: {probability(uncertainty.p_value)} · {t(`по ${number(uncertainty.left_count)} и ${number(uncertainty.right_count)} наблюдениям`, `based on ${number(uncertainty.left_count)} and ${number(uncertainty.right_count)} observations`)}</p>}
          {uncertainty?.status === "not_estimated" && <p>{t("Неопределённость не оценена", "Uncertainty not estimated")}: {label(uncertainty.reason, t("Недостаточно данных.", "Insufficient data."))}</p>}
          <p>{label(data.interpretation, t("Наблюдаемая разница не доказывает причинность.", "The observed difference does not prove causation."))}</p>
        </div>;
      }
      if (item.method === "relationship") {
        const interval = object(data.confidence_interval) ? data.confidence_interval : null;
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>{t("Коэффициент Пирсона", "Pearson coefficient")}</span><strong>{number(data.correlation)}</strong></div>
            <div><span>{t("Групп в расчёте", "Groups in calculation")}</span><strong>{number(data.sample_size)}</strong></div>
            <div><span>{Array.isArray(data.lag_results) ? t("p-value без поправки", "Unadjusted p-value") : "p-value"}</span><strong>{probability(data.p_value)}</strong></div>
          </div>
          {interval && <p>{t("Доверительный интервал", "Confidence interval")}: {number(interval.low)} — {number(interval.high)}</p>}
          {Array.isArray(data.lag_results) && <div className="hypothesis-lags" aria-label={t("Проверенные лаги", "Tested lags")}>
            {data.lag_results.map((lag, i) => object(lag) ? <p key={i}>
              {t("Лаг", "Lag")} {number(lag.lag)}: r = {number(lag.correlation)}, {t("p с поправкой", "adjusted p")} = {probability(lag.adjusted_p_value)}, {t("групп", "groups")} = {number(lag.sample_size)}
            </p> : null)}
          </div>}
          <p>{label(data.interpretation, t("Недостаточно данных для статистического вывода.", "Insufficient data for a statistical conclusion."))}</p>
          {Array.isArray(data.warnings) && data.warnings.map((warning, i) =>
            typeof warning === "string" ? <p key={i}>{warning}</p> : null)}
          <p>{t("Корреляция не доказывает причинность.", "Correlation does not prove causation.")}</p>
        </div>;
      }
      return <p key={index}>{t("Неизвестный тип проверки.", "Unknown test type.")}</p>;
    })}
  </div>;
}
