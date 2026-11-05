import { useLanguage } from "../../i18n";

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

function number(value: unknown, locale: "ru" | "en" = "ru"): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(locale === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 3 }).format(value);
}

function signed(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${number(value)}`;
}

function probability(value: unknown, locale: "ru" | "en" = "ru"): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value > 0 && value < 0.001 ? (locale === "en" ? "<0.001" : "<0,001") : number(value, locale);
}

export function HypothesisEvidence({ evidence }: { evidence: Value & { results: unknown[] } }) {
  const { t, locale } = useLanguage();
  return <div className="hypothesis-evidence" aria-label={t("Проверка гипотезы")}>
    <h4>{label(evidence.statement, t("Проверка гипотезы"))}</h4>
    {evidence.results.map((item, index) => {
      if (!object(item)) return null;
      const data = object(item.data) ? item.data : {};
      if (item.status !== "completed") return <p className="error-text" key={index}>
        Проверка не выполнена. {label(item.error, "Уточните поля и повторите запрос.")}
      </p>;
      if (item.method === "compare") {
        const left = object(data.left) ? data.left : {};
        const right = object(data.right) ? data.right : {};
        const uncertainty = object(data.uncertainty) ? data.uncertainty : null;
        const differenceInterval = uncertainty && object(uncertainty.confidence_interval)
          ? uncertainty.confidence_interval : null;
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>{label(left.label, "Группа 1")}</span><strong>{number(left.value)}</strong></div>
            <div><span>{label(right.label, "Группа 2")}</span><strong>{number(right.value)}</strong></div>
            <div><span>Разница ({label(right.label, "Группа 2")} − {label(left.label, "Группа 1")})</span><strong>{signed(data.delta)}</strong></div>
          </div>
          {typeof data.change_percent === "number" && <p>Изменение: {signed(data.change_percent)}%</p>}
          {differenceInterval && <p>Доверительный интервал разницы: {number(differenceInterval.low)} — {number(differenceInterval.high)}</p>}
          {uncertainty?.status === "estimated" && <p>p-value: {probability(uncertainty.p_value)} · по {number(uncertainty.left_count)} и {number(uncertainty.right_count)} наблюдениям</p>}
          {uncertainty?.status === "not_estimated" && <p>Неопределённость не оценена: {label(uncertainty.reason, "Недостаточно данных.")}</p>}
          <p>{label(data.interpretation, "Наблюдаемая разница не доказывает причинность.")}</p>
        </div>;
      }
      if (item.method === "relationship") {
        const interval = object(data.confidence_interval) ? data.confidence_interval : null;
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>{t("Коэффициент Пирсона")}</span><strong>{number(data.correlation, locale)}</strong></div>
            <div><span>{t("Групп в расчёте")}</span><strong>{number(data.sample_size, locale)}</strong></div>
            <div><span>{t(Array.isArray(data.lag_results) ? "p-value без поправки" : "p-value")}</span><strong>{probability(data.p_value, locale)}</strong></div>
          </div>
          {interval && <p>Доверительный интервал: {number(interval.low)} — {number(interval.high)}</p>}
          {Array.isArray(data.lag_results) && <div className="hypothesis-lags" aria-label="Проверенные лаги">
            {data.lag_results.map((lag, i) => object(lag) ? <p key={i}>
              Лаг {number(lag.lag)}: r = {number(lag.correlation)}, p с поправкой = {probability(lag.adjusted_p_value)}, групп = {number(lag.sample_size)}
            </p> : null)}
          </div>}
          <p>{label(data.interpretation, "Недостаточно данных для статистического вывода.")}</p>
          {Array.isArray(data.warnings) && data.warnings.map((warning, i) =>
            typeof warning === "string" ? <p key={i}>{warning}</p> : null)}
          <p>{t("Корреляция не доказывает причинность.")}</p>
        </div>;
      }
      return <p key={index}>{t("Неизвестный тип проверки.")}</p>;
    })}
  </div>;
}
