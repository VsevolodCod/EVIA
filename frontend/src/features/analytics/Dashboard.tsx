import { useEffect, useMemo, useState } from "react";
import type { Profile, Row, SourceSchema } from "../../api";
import { hasExactStats, numberText, percentText } from "../sources/profileModel";
import { buildDashboardModel, type ChartValue } from "./dashboardModel";
import { defaultPalette, loadPalette, savePalette, seriesColor, type PalettePreference } from "./palette";
import { PaletteEditor } from "./PaletteEditor";
import "./dashboard.css";
import "./dashboardPrint.css";
import "./dashboardControls.css";

function ChartCard({ title, unit, children, detail, detailLabel, footer }: { title: string; unit?: string; children: React.ReactNode; detail?: React.ReactNode; detailLabel?: string; footer?: React.ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  return <section className={`dashboard-card chart-card ${expanded ? "chart-card-expanded" : ""}`} aria-label={expanded ? detailLabel : undefined}>
    <div className="chart-heading"><h3>{title}</h3><div className="chart-heading-actions">{unit && <small>{unit}</small>}<button type="button" className="chart-expand" aria-label={expanded ? "Закрыть график" : `Развернуть график ${title}`} onClick={() => setExpanded(!expanded)}>{expanded ? "✕" : "↗"}</button></div></div>
    {expanded && detail && <div className="chart-detail">{detail}</div>}
    {children}
    {expanded && footer && <div className="chart-detail-footer">{footer}</div>}
  </section>;
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

function MissingBars({ values, color }: { values: ChartValue[]; color: string }) {
  const description = values
    .map((value) => `${value.label}: ${percentText(value.value)}`)
    .join("; ");
  return <div className="quality-chart" role="img" aria-label={`Пропуски по столбцам: ${description}`}>
    {values.map((value) => <div className="quality-row" key={value.label}>
      <span title={value.label}>{value.label}</span>
      <div><i style={{ width: `${value.value}%`, backgroundColor: color }} /></div>
      <b>{percentText(value.value)}</b>
    </div>)}
  </div>;
}

function previewRowsText(count: number) {
  const remainder = Math.abs(count) % 100;
  const lastDigit = remainder % 10;
  const noun = remainder > 10 && remainder < 20 ? "строк" : lastDigit === 1 ? "строка" : lastDigit > 1 && lastDigit < 5 ? "строки" : "строк";
  return `${numberText(count)} ${noun} в предпросмотре источника`;
}

function rowsText(count: number) {
  const remainder = Math.abs(count) % 100;
  const lastDigit = remainder % 10;
  const noun = remainder > 10 && remainder < 20 ? "строк" : lastDigit === 1 ? "строка" : lastDigit > 1 && lastDigit < 5 ? "строки" : "строк";
  return `${numberText(count)} ${noun}`;
}

function fieldsText(count: number) {
  const remainder = Math.abs(count) % 100;
  const lastDigit = remainder % 10;
  const noun = remainder > 10 && remainder < 20 ? "полей" : lastDigit === 1 ? "поле" : lastDigit > 1 && lastDigit < 5 ? "поля" : "полей";
  return `${numberText(count)} ${noun}`;
}

export function Dashboard({
  title,
  sourceLabel,
  scope,
  schema,
  rows,
  profile,
  context = "source",
  fullSourceRows,
}: {
  title: string;
  sourceLabel: string;
  scope: string;
  schema: SourceSchema;
  rows: Row[];
  profile?: Profile;
  context?: "source" | "result";
  fullSourceRows?: number | null;
}) {
  const model = useMemo(() => buildDashboardModel(schema, rows), [schema, rows]);
  const [showPalette, setShowPalette] = useState(false);
  const [showMobileExport, setShowMobileExport] = useState(false);
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
  const sortedNumeric = model.numeric ? [...model.numeric.values].sort((left, right) => left - right) : [];
  const middle = Math.floor(sortedNumeric.length / 2);
  const median = sortedNumeric.length % 2
    ? sortedNumeric[middle]
    : (sortedNumeric[middle - 1] + sortedNumeric[middle]) / 2;
  const standardDeviation = model.numeric
    ? Math.sqrt(model.numeric.values.reduce((sum, value) => sum + (value - model.numeric!.mean) ** 2, 0) / model.numeric.values.length)
    : 0;
  const fullProfile = profile?.coverage === "full";
  const profiledRows = profile
    ? fullProfile
      ? profile.processed_rows
      : profile.sample_size
    : 0;
  const profileLimit = profile?.sample_limit ?? 0;
  const missingFields = Object.values(profile?.columns ?? {}).filter(
    (column) => fullProfile && hasExactStats(column)
      ? column.null_count > 0
      : column.sample_null_count > 0,
  ).length;
  const missingColumns = Object.entries(profile?.columns ?? {})
    .map(([label, column]) => {
      const exact = fullProfile && hasExactStats(column);
      const total = exact
        ? column.non_null_count + column.null_count
        : column.sample_non_null_count + column.sample_null_count;
      return {
        label,
        value: total ? ((exact ? column.null_count : column.sample_null_count) / total) * 100 : 0,
      };
    })
    .filter((column) => column.value > 0)
    .sort((left, right) => right.value - left.value)
    .slice(0, 6);
  const profileCompleteness = profile
    ? (() => {
        const columns = Object.values(profile.columns);
        const cells = columns.reduce(
          (total, column) => total + (fullProfile && hasExactStats(column)
            ? column.non_null_count + column.null_count
            : column.sample_non_null_count + column.sample_null_count),
          0,
        );
        const filled = columns.reduce(
          (total, column) => total + (fullProfile && hasExactStats(column)
            ? column.non_null_count
            : column.sample_non_null_count),
          0,
        );
        return cells ? (filled / cells) * 100 : null;
      })()
    : model.completeness;
  const hasSourceTotal = context === "source" && fullSourceRows != null;
  const profileReady = Boolean(
    profile && profiledRows > 0 && Object.keys(profile.columns).length > 0,
  );
  const scopeDescription = context === "result"
    ? model.rowCount
      ? `В ответе инструмента: ${rowsText(model.rowCount)}`
      : "Инструмент не вернул строк"
    : model.rowCount
      ? previewRowsText(model.rowCount)
      : "В предпросмотре нет строк";
  const exportPdf = () => {
    setShowMobileExport(false);
    const previousTitle = document.title;
    document.title = `EVIA — ${title}`;
    window.addEventListener("afterprint", () => { document.title = previousTitle; }, { once: true });
    window.print();
  };
  const exportCsv = () => {
    const columns = [...new Set(schema.objects.flatMap((object) => object.fields.map((field) => field.name)))];
    const headers = columns.length ? columns : Object.keys(rows[0] ?? {});
    const cell = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [headers.map(cell).join(","), ...rows.map((row) => headers.map((header) => cell(row[header])).join(","))].join("\r\n");
    const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${title.replace(/[\\/:*?"<>|]/g, "_")}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setShowMobileExport(false);
  };

  return <div className="dashboard" data-testid="print-report" data-print-report="true" style={{ "--dashboard-primary": primary, "--dashboard-secondary": secondary } as React.CSSProperties}>
    <div className="dashboard-top">
      <div><h2>{title}</h2><p>{sourceLabel}</p></div>
      <div className="dashboard-actions"><button onClick={() => setShowPalette((open) => !open)} aria-expanded={showPalette}>Цвета</button><button className="desktop-export" onClick={exportPdf}>Экспорт PDF</button><button className="mobile-export-trigger" onClick={() => setShowMobileExport(true)}>Экспорт</button></div>
    </div>
    {showMobileExport && <div className="mobile-export-backdrop" onClick={() => setShowMobileExport(false)}>
      <section className="mobile-export-sheet" aria-label="Экспорт результатов" onClick={(event) => event.stopPropagation()}>
        <div className="mobile-export-heading"><h2>Экспорт результатов</h2><button aria-label="Закрыть экспорт" onClick={() => setShowMobileExport(false)}>✕</button></div>
        <button className="mobile-export-option" onClick={exportCsv}><span>CSV</span><span><strong>Скачать CSV</strong><small>Строки из предпросмотра</small></span><b>↓</b></button>
        <button className="mobile-export-option" onClick={exportPdf}><span>PDF</span><span><strong>Скачать PDF</strong><small>Отчёт с графиками</small></span><b>↓</b></button>
      </section>
    </div>}
    {showPalette && <PaletteEditor colors={colors} gradient={gradient} onChange={updateColors} onClose={() => setShowPalette(false)} />}
    <p className="dashboard-scope">{scopeDescription}</p>
    <div className="kpi-grid" aria-label="Ключевые показатели">
      <section className="dashboard-card"><span>{context === "result" ? "Строк в результате" : hasSourceTotal ? "Строк в источнике" : "Строк в предпросмотре"}</span><strong>{numberText(hasSourceTotal ? fullSourceRows : model.rowCount)}</strong><small>{context === "result" ? "Ответ инструмента" : hasSourceTotal ? "Полный датасет" : "Полный объём неизвестен"}</small></section>
      <section className="dashboard-card"><span>Столбцов</span><strong>{numberText(model.columnCount)}</strong></section>
      <section className="dashboard-card"><span>{profile ? (fullProfile ? "Профиль покрывает весь датасет" : "Профиль покрывает") : "Заполнено ячеек"}</span><strong>{profile ? (profileReady ? fullProfile ? `${rowsText(profiledRows)} обработано` : rowsText(profiledRows) : "Нет данных") : percentText(model.completeness)}</strong><small>{profile ? (profileReady ? fullProfile ? "Точная статистика" : `выборка до ${numberText(profileLimit)} строк` : "Нет строк для анализа") : "доступных ячеек"}</small></section>
      {profile && <section className={`dashboard-card quality-kpi ${profileReady && missingFields ? "needs-attention" : ""}`}><span>Качество данных</span><strong>{!profileReady ? "Нет профиля" : missingFields ? "Нужна проверка" : "Без пропусков"}</strong><small>{!profileReady ? "Нет строк для проверки" : missingFields ? `${fieldsText(missingFields)} с пропусками` : `${percentText(profileCompleteness)} заполнено`}</small></section>}
    </div>
    {hasCharts || missingColumns.length > 0 ? <div className="dashboard-grid">
      {model.timeline && <ChartCard title={`Динамика по полю ${model.timeline.field}`} unit="строки"><LineChart values={model.timeline.values} color={primary} gradient={gradient} label={`Динамика по полю ${model.timeline.field}`} /><p className="visually-hidden">{model.timeline.values.map((point) => `${point.label}: ${numberText(point.value)}`).join("; ")}</p></ChartCard>}
      {model.category && <ChartCard title={`Частые значения: ${model.category.field}`} unit="строки"><HorizontalBars values={model.category.values} color={model.timeline ? secondary : primary} label={`Частые значения поля ${model.category.field}`} /></ChartCard>}
      {model.numeric && <ChartCard title={`Распределение: ${model.numeric.field}`} unit="строки" detailLabel={`Детали распределения ${model.numeric.field}`} detail={<>
        <h4>Статистика распределения</h4>
        <dl className="chart-detail-stats">
          <div><dt>Минимум</dt><dd>{numberText(model.numeric.min)}</dd></div>
          <div><dt>Максимум</dt><dd>{numberText(model.numeric.max)}</dd></div>
          <div><dt>Среднее</dt><dd>{numberText(Number(model.numeric.mean.toFixed(2)))}</dd></div>
          <div><dt>Медиана</dt><dd>{numberText(median)}</dd></div>
          <div><dt>Стандартное отклонение</dt><dd>{numberText(Number(standardDeviation.toFixed(2)))}</dd></div>
        </dl>
      </>} footer={<><h4>Пропуски по столбцам</h4>{missingColumns.length ? <MissingBars values={missingColumns} color={secondary} /> : <p>{profile ? "В профиле пропусков нет" : "Профиль источника ещё не загружен"}</p>}</>}><Histogram values={model.numeric.histogram} color={seriesColor(model.numeric.field, colors)} field={model.numeric.field} /><div className="numeric-summary"><span>Мин. <b>{model.numeric.min.toLocaleString("ru-RU")}</b></span><span>Среднее <b>{model.numeric.mean.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}</b></span><span>Макс. <b>{model.numeric.max.toLocaleString("ru-RU")}</b></span></div></ChartCard>}
      {missingColumns.length > 0 && <ChartCard title="Пропуски по столбцам" unit="доля"><MissingBars values={missingColumns} color={secondary} /></ChartCard>}
    </div> : <div className="dashboard-empty">Для графиков нужны числовые, текстовые или временные поля.</div>}
  </div>;
}
