import { useEffect, useId, useState } from "react";
import type { ToolResult } from "../../api";
import { PaletteEditor } from "../analytics/PaletteEditor";
import { DataTable } from "./DataTable";
import { defaultPalette, loadPalette, savePalette, validatePalette, type PalettePreference } from "../analytics/palette";
import "../analytics/dashboard.css";
import "../analytics/dashboardPrint.css";
import "./generatedDashboard.css";

type ChartType = "kpi" | "line" | "bar" | "scatter" | "table";
type Card = { id: string; type: ChartType; title: string; status: "success" | "error"; definition?: unknown; data?: unknown; error?: { code?: string; message?: string } };
export type Dashboard = { version: 1; title: string; palette?: string[] | null; cards: Card[] };
type Point = { x: string | number | null; y: string | number | null; series?: string | null };
const chartTypes: ChartType[] = ["kpi", "line", "bar", "scatter", "table"];

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function generatedDashboardFrom(result: ToolResult): Dashboard | null {
  if (!result.ok || result.tool_name !== "create_dashboard" || !object(result.data)) return null;
  const data = result.data;
  if (data.version !== 1 || typeof data.title !== "string" || !Array.isArray(data.cards)) return null;
  if (!data.cards.every((card) => object(card) && typeof card.id === "string" &&
    typeof card.title === "string" && chartTypes.includes(card.type as ChartType) &&
    ["success", "error"].includes(String(card.status)))) return null;
  return data as Dashboard;
}

export function generatedChartFrom(result: ToolResult): Dashboard | null {
  if (!result.ok || result.tool_name !== "build_chart" || !object(result.data)) return null;
  const data = result.data;
  if (data.success !== true || typeof data.chart_id !== "string" || !object(data.definition) ||
    typeof data.definition.title !== "string" || !chartTypes.includes(data.definition.type as ChartType)) return null;
  return {
    version: 1,
    title: data.definition.title,
    cards: [{ id: data.chart_id, type: data.definition.type as ChartType, title: data.definition.title,
      status: "success", definition: data.definition, data: data.result }],
  };
}

function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "Нет данных";
  const raw = String(value);
  const decimal = /^(-?)(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!decimal) return raw;
  const integer = decimal[2].replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
  return `${decimal[1]}${integer}${decimal[3] === undefined ? "" : `,${decimal[3]}`}`;
}

function axisFormat(card: Card, axis: "x" | "y"): unknown {
  const data = object(card.data) ? card.data : null;
  const definition = object(card.definition) ? card.definition : null;
  const resultAxis = data && object(data[axis]) ? data[axis] : null;
  const definedAxis = definition && object(definition[axis]) ? definition[axis] : null;
  return resultAxis?.format ?? definedAxis?.format;
}

function formattedNumber(value: unknown, format: unknown): string {
  const number = numeric(value);
  if (number === null || !object(format)) return displayValue(value);
  const decimals = typeof format.decimals === "number" && Number.isInteger(format.decimals)
    ? Math.max(0, Math.min(6, format.decimals)) : 2;
  const options: Intl.NumberFormatOptions = { minimumFractionDigits: decimals, maximumFractionDigits: decimals };
  if (format.type === "integer") { options.minimumFractionDigits = 0; options.maximumFractionDigits = 0; }
  if (format.type === "percent") options.style = "percent";
  if (format.type === "currency" && typeof format.currency === "string") {
    options.style = "currency";
    options.currency = format.currency;
    options.minimumFractionDigits = decimals;
  }
  try { return new Intl.NumberFormat("ru-RU", options).format(number); }
  catch { return displayValue(value); }
}

function lineData(value: unknown): { points: Point[]; xLabel: string; yLabel: string } | null {
  if (!object(value) || !Array.isArray(value.points)) return null;
  const points = value.points.filter((item): item is Point =>
    object(item) && (typeof item.x === "string" || typeof item.x === "number" || item.x === null) &&
    (typeof item.y === "string" || typeof item.y === "number" || item.y === null));
  const x = object(value.x) ? value.x : {};
  const y = object(value.y) ? value.y : {};
  return { points, xLabel: String(x.label ?? x.field ?? "Категория"), yLabel: String(y.label ?? y.field ?? "Значение") };
}

function calculationPassport(card: Card): { source: string; formula: string; period: string; filters: string[]; grouping?: string; snapshot?: string; schemaVersion?: number } | null {
  const definition = card.definition;
  if (!object(definition)) return null;
  const measure = definition.type === "kpi" ? definition.field : definition.y;
  const fields = Array.isArray(definition.fields) ? definition.fields.filter(object) : [];
  const source = object(measure) && typeof measure.source_id === "string"
    ? measure.source_id : fields.length && typeof fields[0].source_id === "string" ? fields[0].source_id : null;
  if (!source) return null;
  const aggregate = definition.type === "kpi" ? definition.aggregate : object(measure) ? measure.aggregate : null;
  let formula: string;
  if (typeof aggregate === "string" && object(measure) && typeof measure.field === "string")
    formula = `${aggregate.toUpperCase()}(${measure.field})`;
  else if (definition.type === "scatter" && object(definition.x) && object(definition.y))
    formula = `X: ${String(definition.x.field)}; Y: ${String(definition.y.field)}`;
  else if (definition.type === "table" && fields.length)
    formula = `Поля: ${fields.map(item => String(item.field)).join(", ")}`;
  else return null;
  const filters = Array.isArray(definition.filters) ? definition.filters.flatMap((item) => {
    if (!object(item) || !object(item.field) || typeof item.field.field !== "string" || typeof item.operator !== "string") return [];
    const operators: Record<string, string> = { eq: "=", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "в", not_in: "не в", between: "между", is_null: "пусто", is_not_null: "не пусто" };
    const value = Array.isArray(item.value) ? item.value.map(String).join(", ") : item.value == null ? "" : String(item.value);
    return [`${item.field.field} ${operators[item.operator] ?? item.operator}${value ? ` ${value}` : ""}`];
  }) : [];
  const result = object(card.data) ? card.data : null;
  const provenance = result && Array.isArray(result.provenance)
    ? result.provenance.find((item) => object(item) && item.source_id === source) : null;
  const grains: Record<string, string> = { day: "По дням", week: "По неделям", month: "По месяцам", quarter: "По кварталам", year: "По годам" };
  const x = object(definition.x) ? definition.x : null;
  return {
    source,
    formula,
    period: filters.length ? "Применены фильтры" : "Весь источник без фильтров",
    filters,
    grouping: (definition.type === "line" || definition.type === "bar") && x && typeof x.field === "string"
      ? `${typeof x.time_grain === "string" ? grains[x.time_grain] ?? x.time_grain : "По исходным значениям"}: ${x.field}`
      : undefined,
    snapshot: object(provenance) && typeof provenance.snapshot_id === "string" ? provenance.snapshot_id : undefined,
    schemaVersion: object(provenance) && typeof provenance.schema_version === "number" ? provenance.schema_version : undefined,
  };
}

function ResultLine({ card, colors, gradient }: { card: Card; colors: string[]; gradient: boolean }) {
  const chart = lineData(card.data);
  const format = axisFormat(card, "y");
  const gradientId = useId().replaceAll(":", "");
  if (!chart || !chart.points.length) return <p className="generated-empty">Нет точек для графика.</p>;
  const labels = [...new Set(chart.points.map((point) => String(point.x ?? "—")))];
  const series = [...new Set(chart.points.map((point) => point.series ?? ""))];
  const values = chart.points.map((point) => numeric(point.y)).filter((value): value is number => value !== null);
  if (!values.length) return <p className="generated-empty">Нет числовых значений для графика.</p>;
  const width = 720; const height = 260; const left = 54; const right = 16; const top = 18; const bottom = 42;
  const minimum = Math.min(0, ...values); const maximum = Math.max(0, ...values);
  const span = maximum - minimum || 1;
  const x = (label: string) => left + ((width - left - right) * labels.indexOf(label)) / Math.max(labels.length - 1, 1);
  const y = (value: number) => top + ((height - top - bottom) * (maximum - value)) / span;
  const plotted = series.map((name, index) => ({
    name, color: colors[index % colors.length],
    points: chart.points.filter((point) => (point.series ?? "") === name && numeric(point.y) !== null),
  }));
  return <>
    {object(card.data) && card.data.limit_reached === true && <p className="generated-limit-note">
      Показано точек: {chart.points.length}. Достигнут лимит выдачи; в источнике могут быть другие группы. Уточните период или фильтры.
    </p>}
    <svg className="generated-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${card.title}: ${chart.yLabel} по ${chart.xLabel}`}>
      <defs><linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1"><stop stopColor={colors[0]} stopOpacity=".2" /><stop offset="1" stopColor={colors[0]} stopOpacity="0" /></linearGradient></defs>
      {[0, .5, 1].map((step) => {
        const value = minimum + step * span;
        return <g key={step}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text x={left - 10} y={y(value) + 4} textAnchor="end">{formattedNumber(Number(value.toFixed(2)), format)}</text></g>;
      })}
      {plotted.map(({ name, color, points }, index) => {
        const positions = points.map((point) => [x(String(point.x ?? "—")), y(numeric(point.y) ?? 0)]);
        const line = positions.map(([px, py]) => `${px},${py}`).join(" ");
        const baseline = y(0);
        return <g key={name}>
          {gradient && series.length === 1 && positions.length > 1 && <path d={`M ${positions[0][0]} ${baseline} L ${positions.map(([px, py]) => `${px} ${py}`).join(" L ")} L ${positions.at(-1)![0]} ${baseline} Z`} fill={`url(#${gradientId})`} />}
          <polyline points={line} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" data-testid={`generated-series-${index}`} />
          {points.map((point, pointIndex) => <circle key={`${point.x}-${pointIndex}`} cx={x(String(point.x ?? "—"))} cy={y(numeric(point.y) ?? 0)} r="4" fill={color} tabIndex={0} aria-label={`${point.x}: ${formattedNumber(point.y, format)}`}><title>{`${point.x}: ${formattedNumber(point.y, format)}`}</title></circle>)}
        </g>;
      })}
      {labels.filter((_, index) => index % Math.max(1, Math.ceil(labels.length / 6)) === 0).map((label) => <text key={label} x={x(label)} y={height - 13} textAnchor="middle">{label.length > 12 ? `${label.slice(0, 10)}…` : label}</text>)}
    </svg>
    {series.length > 1 && <div className="generated-legend">{plotted.map(({ name, color }) => <span key={name}><i style={{ backgroundColor: color }} />{name}</span>)}</div>}
    <div className="generated-axis-label">{chart.xLabel} · {chart.yLabel}</div>
  </>;
}

function LimitNote({ data, count, unit = "точек" }: { data: unknown; count: number; unit?: string }) {
  return object(data) && data.limit_reached === true ? <p className="generated-limit-note">
    Показано {unit}: {count}. Достигнут лимит выдачи; в источнике могут быть другие строки или группы. Уточните фильтры.
  </p> : null;
}

function ResultBar({ card, colors }: { card: Card; colors: string[] }) {
  const chart = lineData(card.data);
  const format = axisFormat(card, "y");
  if (!chart || !chart.points.length) return <p className="generated-empty">Нет столбцов для графика.</p>;
  const values = chart.points.map(point => numeric(point.y)).filter((value): value is number => value !== null);
  if (!values.length) return <p className="generated-empty">Нет числовых значений для графика.</p>;
  const width = Math.max(720, chart.points.length * 32 + 70);
  const height = 260; const left = 54; const right = 16; const top = 18; const bottom = 42;
  const minimum = Math.min(0, ...values); const maximum = Math.max(0, ...values);
  const scale = Math.max(1, Math.abs(minimum), Math.abs(maximum));
  const span = maximum / scale - minimum / scale || 1;
  const y = (value: number) => top + (height - top - bottom) * ((maximum / scale - value / scale) / span);
  const baseline = y(0);
  const x = (index: number) => left + (width - left - right) * ((index + .5) / chart.points.length);
  const barWidth = Math.min(24, (width - left - right) / chart.points.length * .7);
  const stride = Math.max(1, Math.ceil(chart.points.length / 10));
  const hasSeries = object(card.definition) && object(card.definition.series);
  const seriesName = (point: Point) => point.series == null || point.series === "" ? "Нет значения" : String(point.series);
  const series = hasSeries ? [...new Set(chart.points.map(seriesName))] : [];
  return <>
    <LimitNote data={card.data} count={chart.points.length} />
    <div className="generated-chart-scroll" role="region" aria-label={`Прокрутка графика ${card.title}`} tabIndex={0}>
      <svg className="generated-bar-chart" width={width} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${card.title}: ${chart.yLabel} по ${chart.xLabel}`}>
        <line x1={left} x2={width - right} y1={baseline} y2={baseline} stroke="#82968b" />
        {chart.points.map((point, index) => {
          const value = numeric(point.y);
          if (value === null) return null;
          const topY = Math.min(y(value), baseline);
          const name = hasSeries ? `${point.x} · ${seriesName(point)}` : String(point.x);
          const seriesIndex = hasSeries ? series.indexOf(seriesName(point)) : 0;
          return <rect key={index} data-bar="true" x={x(index) - barWidth / 2} y={topY} width={barWidth}
            height={Math.abs(y(value) - baseline)} fill={colors[Math.max(seriesIndex, 0) % colors.length]} rx="2" tabIndex={0}
            aria-label={`${name}: ${formattedNumber(point.y, format)}`}><title>{`${name}: ${formattedNumber(point.y, format)}`}</title></rect>;
        })}
        {chart.points.map((point, index) => index % stride === 0 && <text key={index} x={x(index)} y={height - 13} textAnchor="middle">
          {String(point.x ?? "—").slice(0, 12)}
        </text>)}
      </svg>
    </div>
    {series.length > 1 && <div className="generated-legend">{series.map((name, index) =>
      <span key={name}><i style={{ backgroundColor: colors[index % colors.length] }} />{name}</span>
    )}</div>}
    <div className="generated-axis-label">{chart.xLabel} · {chart.yLabel}</div>
  </>;
}

function ResultScatter({ card, color }: { card: Card; color: string }) {
  const chart = lineData(card.data);
  const xFormat = axisFormat(card, "x");
  const yFormat = axisFormat(card, "y");
  if (!chart || !chart.points.length) return <p className="generated-empty">Нет точек для диаграммы.</p>;
  const points = chart.points.flatMap(point => {
    const x = numeric(point.x); const y = numeric(point.y);
    return x === null || y === null ? [] : [{ x, y }];
  });
  if (!points.length) return <p className="generated-empty">Нет числовых пар для диаграммы.</p>;
  const width = 720; const height = 260; const left = 54; const right = 18; const top = 18; const bottom = 42;
  const xMin = Math.min(...points.map(point => point.x)); const xMax = Math.max(...points.map(point => point.x));
  const yMin = Math.min(...points.map(point => point.y)); const yMax = Math.max(...points.map(point => point.y));
  const coordinate = (value: number, min: number, max: number) => {
    const scale = Math.max(1, Math.abs(min), Math.abs(max));
    return (value / scale - min / scale) / (max / scale - min / scale || 1);
  };
  return <>
    <LimitNote data={card.data} count={points.length} />
    <svg className="generated-scatter-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${card.title}: ${chart.yLabel} по ${chart.xLabel}`}>
      <line x1={left} x2={left} y1={top} y2={height - bottom} stroke="#82968b" />
      <line x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} stroke="#82968b" />
      {points.map((point, index) => <circle key={index} data-point="true"
        cx={left + coordinate(point.x, xMin, xMax) * (width - left - right)}
        cy={height - bottom - coordinate(point.y, yMin, yMax) * (height - top - bottom)}
        r="5" fill={color} fillOpacity=".75" tabIndex={0} aria-label={`${formattedNumber(point.x, xFormat)}; ${formattedNumber(point.y, yFormat)}`}>
        <title>{`${formattedNumber(point.x, xFormat)}; ${formattedNumber(point.y, yFormat)}`}</title>
      </circle>)}
    </svg>
    <div className="generated-axis-label">X: {chart.xLabel} · Y: {chart.yLabel}</div>
  </>;
}

function ResultTable({ card }: { card: Card }) {
  const data = object(card.data) ? card.data : null;
  const columns = data && Array.isArray(data.columns) ? data.columns.filter((name): name is string => typeof name === "string") : [];
  const rows = data && Array.isArray(data.rows) ? data.rows.filter(object) : [];
  if (!columns.length) return <p className="generated-empty">Нет столбцов для таблицы.</p>;
  return <>
    <LimitNote data={card.data} count={rows.length} unit="строк" />
    <DataTable rows={rows} columns={columns} label={card.title} />
  </>;
}

function GeneratedCard({ card, preference }: { card: Card; preference: PalettePreference }) {
  const [view, setView] = useState<"line" | "bar">(card.type === "line" ? "line" : "bar");
  useEffect(() => setView(card.type === "line" ? "line" : "bar"), [card.id, card.type]);
  const grouped = card.status === "success" && (card.type === "line" || card.type === "bar");
  const activeType = grouped ? view : card.type;
  const passport = card.status === "success" ? calculationPassport(card) : null;
  return <section className={`dashboard-card generated-card generated-${activeType}-card`}>
    <div className="chart-heading"><h3>{card.title}</h3>{card.status === "success" && <small>{({ kpi: "Показатель", line: "Динамика", bar: "Сравнение", scatter: "Связь", table: "Таблица" } as const)[activeType]}</small>}</div>
    {grouped && <div className="generated-view-switch" role="group" aria-label={`Вид графика «${card.title}»`}
      title="Линия и столбцы показывают те же вычисленные группы. Точки и таблица требуют нового расчёта исходных строк.">
      <button type="button" aria-pressed={view === "line"} onClick={() => setView("line")}>Линия</button>
      <button type="button" aria-pressed={view === "bar"} onClick={() => setView("bar")}>Столбцы</button>
    </div>}
    {card.status === "error" ? <p className="generated-empty">Не удалось рассчитать эту карточку.</p>
      : card.type === "kpi" && object(card.data) ? <strong className="generated-value">{formattedNumber(card.data.value,
          card.data.format ?? (object(card.definition) ? card.definition.format : null))}</strong>
        : activeType === "line" ? <ResultLine card={card} colors={preference.colors} gradient={preference.gradient} />
          : activeType === "bar" ? <ResultBar card={card} colors={preference.colors} />
            : activeType === "scatter" ? <ResultScatter card={card} color={preference.colors[0]} />
              : activeType === "table" ? <ResultTable card={card} /> : null}
    {passport && <details className="generated-passport">
      <summary>Паспорт расчёта</summary>
      <dl><div><dt>Формула</dt><dd>{passport.formula}</dd></div><div><dt>Источник</dt><dd>{passport.source}</dd></div><div><dt>Период</dt><dd>{passport.period}</dd></div>
        {passport.filters.length > 0 && <div><dt>Фильтры</dt><dd>{passport.filters.join("; ")}</dd></div>}
        {passport.grouping && <div><dt>Группировка</dt><dd>{passport.grouping}</dd></div>}
        {passport.snapshot && <div><dt>Снимок данных</dt><dd>{passport.snapshot}</dd></div>}
        {passport.schemaVersion !== undefined && <div><dt>Версия схемы</dt><dd>{passport.schemaVersion}</dd></div>}
      </dl>
    </details>}
  </section>;
}

export function GeneratedDashboard({ dashboard, scope, sourceLabel }: { dashboard: Dashboard; scope: string; sourceLabel?: string }) {
  const [showPalette, setShowPalette] = useState(false);
  const supplied = (() => { try { return dashboard.palette ? validatePalette(dashboard.palette) : defaultPalette.colors; } catch { return defaultPalette.colors; } })();
  const [preference, setPreference] = useState<PalettePreference>(() => loadPalette(scope) ?? { colors: supplied, gradient: false });
  useEffect(() => setPreference(loadPalette(scope) ?? { colors: supplied, gradient: false }), [scope, dashboard]);
  const changePalette = (colors: string[], gradient: boolean) => {
    const next = { colors, gradient };
    setPreference(next);
    savePalette(scope, next);
  };
  const exportPdf = () => {
    const previousTitle = document.title;
    document.title = `EVIA — ${dashboard.title}`;
    window.addEventListener("afterprint", () => { document.title = previousTitle; }, { once: true });
    window.print();
  };
  return <div className="dashboard generated-dashboard" data-print-report="true" style={{ "--dashboard-primary": preference.colors[0], "--dashboard-secondary": preference.colors[1] } as React.CSSProperties}>
    <div className="dashboard-top"><div><h2>{dashboard.title}</h2>{sourceLabel && <p>{sourceLabel}</p>}</div>
      <div className="dashboard-actions"><button type="button" aria-expanded={showPalette} onClick={() => setShowPalette(!showPalette)}>Цвета</button><button type="button" onClick={exportPdf}>Печать / PDF</button></div>
    </div>
    {showPalette && <PaletteEditor colors={preference.colors} gradient={preference.gradient} onChange={changePalette} onClose={() => setShowPalette(false)} />}
    <div className="generated-grid">
      {dashboard.cards.map((card) => <GeneratedCard key={card.id} card={card} preference={preference} />)}
    </div>
  </div>;
}
