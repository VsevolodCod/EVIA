import { useEffect, useMemo, useState } from "react";
import type { Row, SourceSchema } from "../../api";
import { numberText, percentText } from "../sources/profileModel";
import { buildDashboardModel, type ChartValue } from "./dashboardModel";
import { defaultPalette, loadPalette, savePalette, seriesColor, type PalettePreference } from "./palette";
import { PaletteEditor } from "./PaletteEditor";
import "./dashboard.css";
import "./dashboardPrint.css";
import "./dashboardControls.css";

function ChartCard({ title, unit, children }: { title: string; unit?: string; children: React.ReactNode }) {
  return <section className="dashboard-card chart-card"><div className="chart-heading"><h3>{title}</h3>{unit && <small>{unit}</small>}</div>{children}</section>;
}

function HorizontalBars({ values, color, label }: { values: ChartValue[]; color: string; label: string }) {
  const maximum = Math.max(...values.map((value) => value.value), 1);
  return <div className="bar-chart" role="img" aria-label={label}>
    {values.map((value) => <div className="bar-row" key={value.label}><span title={value.label}>{value.label}</span><div><i style={{ width: `${(value.value / maximum) * 100}%`, backgroundColor: color }} data-testid="chart-color-1" data-color={color} /></div><b>{numberText(value.value)}</b></div>)}
  </div>;
}

function LineChart({ values, color, gradient, label }: { values: ChartValue[]; color: string; gradient: boolean; label: string }) {
  const width = 640; const height = 220; const left = 32; const right = 12; const top = 18; const bottom = 34;
  const maximum = Math.max(...values.map((point) => point.value), 1);
  const x = (index: number) => left + ((width - left - right) * index) / Math.max(values.length - 1, 1);
  const y = (value: number) => height - bottom - ((height - top - bottom) * value) / maximum;
  const points = values.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `M ${x(0)} ${height - bottom} L ${points.replaceAll(",", " ").replaceAll(" ", " ")} L ${x(values.length - 1)} ${height - bottom} Z`;
  return <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
    <defs><linearGradient id="chart-area" x1="0" x2="0" y1="0" y2="1"><stop stopColor={color} stopOpacity=".22"/><stop offset="1" stopColor={color} stopOpacity="0"/></linearGradient></defs>
    {[0, .5, 1].map((step) => <line key={step} x1={left} x2={width - right} y1={y(maximum * step)} y2={y(maximum * step)} />)}
    {gradient && <path d={area} fill="url(#chart-area)" />}
    <polyline points={points} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" data-testid="chart-color-0" data-color={color} />
    {values.map((point, index) => <g key={point.label} tabIndex={0} aria-label={`${point.label}: ${numberText(point.value)}`}><circle cx={x(index)} cy={y(point.value)} r="4" fill={color}><title>{`${point.label}: ${numberText(point.value)}`}</title></circle><text x={x(index)} y={height - 10} textAnchor="middle">{point.label}</text></g>)}
  </svg>;
}

function Histogram({ values, color, field }: { values: ChartValue[]; color: string; field: string }) {
  const maximum = Math.max(...values.map((value) => value.value), 1);
  return <div className="histogram" role="img" aria-label={`Распределение поля ${field}`}>
    {values.map((value) => <div key={value.label}><i style={{ height: `${(value.value / maximum) * 100}%`, backgroundColor: color }}><title>{`${value.label}: ${value.value} строк`}</title></i><span>{value.label}</span></div>)}
  </div>;
}

function previewRowsText(count: number) {
  const remainder = Math.abs(count) % 100;
  const lastDigit = remainder % 10;
  const noun = remainder > 10 && remainder < 20 ? "строк" : lastDigit === 1 ? "строка" : lastDigit > 1 && lastDigit < 5 ? "строки" : "строк";
  return `${numberText(count)} ${noun} в предпросмотре источника`;
}

export function Dashboard({ title, sourceLabel, scope, schema, rows }: { title: string; sourceLabel: string; scope: string; schema: SourceSchema; rows: Row[] }) {
  const model = useMemo(() => buildDashboardModel(schema, rows), [schema, rows]);
  const [showPalette, setShowPalette] = useState(false);
  const fallbackPreference: PalettePreference = { colors: defaultPalette.colors, gradient: false };
  const [preference, setPreference] = useState<PalettePreference>(() => loadPalette(scope) ?? fallbackPreference);
  useEffect(() => setPreference(loadPalette(scope) ?? fallbackPreference), [scope]);
  const updateColors = (colors: string[], gradient: boolean) => {
    const next = { colors, gradient };
    setPreference(next);
    savePalette(scope, next);
  };
  const { colors, gradient } = preference;
  const primary = colors[0]; const secondary = colors[1];
  const hasCharts = Boolean(model.category || model.numeric || model.timeline);
  const exportPdf = () => {
    const previousTitle = document.title;
    document.title = `EVIA — ${title}`;
    window.addEventListener("afterprint", () => { document.title = previousTitle; }, { once: true });
    window.print();
  };

  return <div className="dashboard" data-testid="print-report" data-print-report="true" style={{ "--dashboard-primary": primary, "--dashboard-secondary": secondary } as React.CSSProperties}>
    <div className="dashboard-top">
      <div><h2>{title}</h2><p>{sourceLabel}</p></div>
      <div className="dashboard-actions"><button onClick={() => setShowPalette((open) => !open)} aria-expanded={showPalette}>Цвета</button><button onClick={exportPdf}>Экспорт PDF</button></div>
    </div>
    {showPalette && <PaletteEditor colors={colors} gradient={gradient} onChange={updateColors} onClose={() => setShowPalette(false)} />}
    <p className="dashboard-scope">{model.rowCount ? previewRowsText(model.rowCount) : "В предпросмотре нет строк"}</p>
    <div className="kpi-grid" aria-label="Ключевые показатели">
      <section className="dashboard-card"><span>Строк в выборке</span><strong>{numberText(model.rowCount)}</strong></section>
      <section className="dashboard-card"><span>Столбцов</span><strong>{numberText(model.columnCount)}</strong></section>
      <section className="dashboard-card"><span>Заполнено ячеек</span><strong>{percentText(model.completeness)}</strong></section>
    </div>
    {hasCharts ? <div className="dashboard-grid">
      {model.timeline && <ChartCard title={`Динамика по полю ${model.timeline.field}`} unit="строки"><LineChart values={model.timeline.values} color={primary} gradient={gradient} label={`Динамика по полю ${model.timeline.field}`} /><p className="visually-hidden">{model.timeline.values.map((point) => `${point.label}: ${numberText(point.value)}`).join("; ")}</p></ChartCard>}
      {model.category && <ChartCard title={`Частые значения: ${model.category.field}`} unit="строки"><HorizontalBars values={model.category.values} color={model.timeline ? secondary : primary} label={`Частые значения поля ${model.category.field}`} /></ChartCard>}
      {model.numeric && <ChartCard title={`Распределение: ${model.numeric.field}`} unit="строки"><Histogram values={model.numeric.histogram} color={seriesColor(model.numeric.field, colors)} field={model.numeric.field} /><div className="numeric-summary"><span>Мин. <b>{model.numeric.min.toLocaleString("ru-RU")}</b></span><span>Среднее <b>{model.numeric.mean.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}</b></span><span>Макс. <b>{model.numeric.max.toLocaleString("ru-RU")}</b></span></div></ChartCard>}
    </div> : <div className="dashboard-empty">Для графиков нужны числовые, текстовые или временные поля.</div>}
  </div>;
}
