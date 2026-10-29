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

export function HypothesisEvidence({ evidence }: { evidence: Value & { results: unknown[] } }) {
  return <div className="hypothesis-evidence" aria-label="Проверка гипотезы">
    <h4>{label(evidence.statement, "Проверка гипотезы")}</h4>
    {evidence.results.map((item, index) => {
      if (!object(item)) return null;
      const data = object(item.data) ? item.data : {};
      if (item.status !== "completed") return <p className="error-text" key={index}>
        Проверка не выполнена. {label(item.error, "Уточните поля и повторите запрос.")}
      </p>;
      if (item.method === "compare") {
        const left = object(data.left) ? data.left : {};
        const right = object(data.right) ? data.right : {};
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>{label(left.label, "Группа 1")}</span><strong>{number(left.value)}</strong></div>
            <div><span>{label(right.label, "Группа 2")}</span><strong>{number(right.value)}</strong></div>
            <div><span>Разница</span><strong>{signed(data.delta)}</strong></div>
          </div>
          {typeof data.change_percent === "number" && <p>Изменение: {signed(data.change_percent)}%</p>}
          <p>{label(data.interpretation, "Наблюдаемая разница не доказывает причинность.")}</p>
        </div>;
      }
      if (item.method === "relationship") {
        const interval = object(data.confidence_interval) ? data.confidence_interval : null;
        return <div className="hypothesis-check" key={index}>
          <div className="hypothesis-values">
            <div><span>Коэффициент Пирсона</span><strong>{number(data.correlation)}</strong></div>
            <div><span>Групп в расчёте</span><strong>{number(data.sample_size)}</strong></div>
            <div><span>p-value</span><strong>{number(data.p_value)}</strong></div>
          </div>
          {interval && <p>Доверительный интервал: {number(interval.low)} — {number(interval.high)}</p>}
          <p>{label(data.interpretation, "Недостаточно данных для статистического вывода.")}</p>
          {Array.isArray(data.warnings) && data.warnings.map((warning, i) =>
            typeof warning === "string" ? <p key={i}>{warning}</p> : null)}
          <p>Корреляция не доказывает причинность.</p>
        </div>;
      }
      return <p key={index}>Неизвестный тип проверки.</p>;
    })}
  </div>;
}
