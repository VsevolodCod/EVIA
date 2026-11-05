import { useEffect, useMemo, useState } from "react";
import type { Profile, Row, Source, SourceSchema } from "../../api";
import type { Entry } from "../chat/types";
import { hasExactStats, numberText, percentText } from "../sources/profileModel";
import { buildDashboardModel, type ChartValue } from "./dashboardModel";
import { defaultPalette, loadPalette, savePalette, seriesColor, type PalettePreference } from "./palette";
import { PaletteEditor } from "./PaletteEditor";
import { DataTable } from "../results/DataTable";
import { serializeCsv } from "../results/csvExport";
import { ReportBuilder } from "./ReportBuilder";
import { useLanguage } from "../../i18n";
import "./dashboard.css";
import "./dashboardPrint.css";
import "./dashboardControls.css";

function ChartCard({ title, unit, children, detail, detailLabel, footer }: { title: string; unit?: string; children: React.ReactNode; detail?: React.ReactNode; detailLabel?: string; footer?: React.ReactNode }) {
  const { t } = useLanguage();
  const [expanded, setExpanded] = useState(false);
  return <section className={`dashboard-card chart-card ${expanded ? "chart-card-expanded" : ""}`} aria-label={expanded ? detailLabel : undefined}>
    <div className="chart-heading"><h3>{title}</h3><div className="chart-heading-actions">{unit && <small>{unit}</small>}<button type="button" className="chart-expand" aria-label={expanded ? t("Закрыть график") : `${t("Развернуть график")} ${title}`} onClick={() => setExpanded(!expanded)}>{expanded ? "✕" : "↗"}</button></div></div>
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
  const { t } = useLanguage();
  const maximum = Math.max(...values.map((value) => value.value), 1);
  return <div className="histogram" role="img" aria-label={`${t("Распределение поля")} ${field}`}>
    {values.map((value) => <div key={value.label}><i style={{ height: `${(value.value / maximum) * 100}%`, backgroundColor: color }}><title>{`${value.label}: ${value.value} ${t("строк")}`}</title></i><span>{value.label}</span></div>)}
  </div>;
}

function MissingBars({ values, color }: { values: ChartValue[]; color: string }) {
  const { t } = useLanguage();
  const description = values
    .map((value) => `${value.label}: ${percentText(value.value)}`)
    .join("; ");
  return <div className="quality-chart" role="img" aria-label={`${t("Пропуски по столбцам")}: ${description}`}>
    {values.map((value) => <div className="quality-row" key={value.label}>
      <span title={value.label}>{value.label}</span>
      <div><i style={{ width: `${value.value}%`, backgroundColor: color }} /></div>
      <b>{percentText(value.value)}</b>
    </div>)}
  </div>;
}

function fieldsText(count: number, locale: "ru" | "en") {
  if (locale === "en") return `${numberText(count)} ${count === 1 ? "field" : "fields"}`;
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
  onOpenData,
  source,
  reportEntries = [],
}: {
  title: string;
  sourceLabel: string;
  scope: string;
  schema: SourceSchema;
  rows: Row[];
  profile?: Profile;
  context?: "source" | "result";
  fullSourceRows?: number | null;
  onOpenData?: () => void;
  source?: Source;
  reportEntries?: Entry[];
}) {
  const { locale, t } = useLanguage();
  const model = useMemo(() => buildDashboardModel(schema, rows), [schema, rows]);
  const [showPalette, setShowPalette] = useState(false);
  const [showMobileExport, setShowMobileExport] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  useEffect(() => setReportOpen(false), [source?.source_id]);
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
    profile && (fullProfile ? (profile.processed_rows ?? 0) : profile.sample_size) > 0 && Object.keys(profile.columns).length > 0,
  );
  const exportPdf = () => {
    setShowMobileExport(false);
    if (context === "source" && source) {
      setReportOpen(true);
      return;
    }
    const previousTitle = document.title;
    document.title = `EVIA — ${title}`;
    window.addEventListener("afterprint", () => { document.title = previousTitle; }, { once: true });
    window.print();
  };
  const exportCsv = () => {
    const columns = [...new Set(schema.objects.flatMap((object) => object.fields.map((field) => field.name)))];
    const headers = columns.length ? columns : Object.keys(rows[0] ?? {});
    const csv = serializeCsv({ columns: headers, rows: rows.map((row) => headers.map((header) => row[header])), truncated: false });
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${title.replace(/[\\/:*?"<>|]/g, "_")}.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setShowMobileExport(false);
  };

  return <div className="dashboard" data-testid="print-report" data-print-report="true" style={{ "--dashboard-primary": primary, "--dashboard-secondary": secondary } as React.CSSProperties}>
    {reportOpen && source && <ReportBuilder source={source} schema={schema} rows={rows} profile={profile}
      entries={reportEntries} onClose={() => setReportOpen(false)} />}
    <div className="dashboard-top">
      <div><h2>{t(title)}</h2>{context === "result" && <p>{sourceLabel}</p>}</div>
      <div className="dashboard-actions"><button onClick={exportCsv}>{t(context === "source" ? "Скачать предпросмотр" : "Скачать результат")}</button><button className="desktop-export" onClick={exportPdf}>{t(source ? "Собрать PDF-отчёт" : "Печать / PDF")}</button><button className="mobile-export-trigger" onClick={() => setShowMobileExport(true)}>{t("Ещё")}</button></div>
    </div>
    {showMobileExport && <div className="mobile-export-backdrop" onClick={() => setShowMobileExport(false)}>
      <section className="mobile-export-sheet" aria-label={t("Экспорт результатов")} onClick={(event) => event.stopPropagation()}>
        <div className="mobile-export-heading"><h2>{t("Экспорт результатов")}</h2><button aria-label={t("Закрыть экспорт")} onClick={() => setShowMobileExport(false)}>✕</button></div>
        <button className="mobile-export-option" onClick={exportCsv}><span>CSV</span><span><strong>{t("Скачать CSV")}</strong><small>{t(context === "source" ? "Строки из предпросмотра" : "Строки результата")}</small></span><b>↓</b></button>
        <button className="mobile-export-option" onClick={exportPdf}><span>PDF</span><span><strong>{t(source ? "Собрать PDF-отчёт" : "Печать / PDF")}</strong><small>{t(source ? "Выберите выводы и сохраните файл" : "Сохраните PDF в окне печати")}</small></span><b>↗</b></button>
        <button className="mobile-export-option" onClick={() => { setShowMobileExport(false); setShowPalette(true); }}><span>●</span><span><strong>{t("Цвета графиков")}</strong><small>{t("Настроить палитру")}</small></span><b>↗</b></button>
      </section>
    </div>}
    {showPalette && <PaletteEditor colors={colors} gradient={gradient} onChange={updateColors} onClose={() => setShowPalette(false)} />}
    {!rows.length && <p className="dashboard-empty-state">{t(context === "source" ? "В предпросмотре нет строк" : "Инструмент не вернул строк")}</p>}
    <div className="kpi-grid" aria-label={t("Ключевые показатели")}>
      <section className="dashboard-card"><span>{t(context === "result" ? "Строк в результате" : hasSourceTotal ? "Строк в источнике" : "Строк в предпросмотре")}</span><strong>{numberText(hasSourceTotal ? fullSourceRows : model.rowCount)}</strong><small>{t(context === "result" ? "Ответ инструмента" : hasSourceTotal ? "Полный датасет" : "Полный объём неизвестен")}</small></section>
      <section className="dashboard-card"><span>{t("Столбцов")}</span><strong>{numberText(model.columnCount)}</strong></section>
      {!profile && <section className="dashboard-card"><span>{t("Заполнено ячеек")}</span><strong>{percentText(model.completeness)}</strong></section>}
    {profile && <section className={`dashboard-card quality-kpi ${profileReady && missingFields ? "needs-attention" : ""}`}><span>{t(fullProfile ? "Заполненность источника" : "Заполненность выборки")}</span><strong>{!profileReady ? t("Нет профиля") : percentText(profileCompleteness)}</strong><small>{!profileReady ? t("Нет строк для проверки") : missingFields ? `${fieldsText(missingFields, locale)} ${t("с пропусками")}` : fullProfile ? t("Пропусков не найдено") : t("В выборке пропусков нет")}</small></section>}
    </div>
    {rows.length > 0 && <section className="dashboard-preview" aria-label={context === "source" ? "Первые строки источника" : "Таблица результата"}>
      <div className="dashboard-section-heading"><h3>{t(context === "source" ? "Первые строки" : "Таблица результата")}</h3>{onOpenData && <button type="button" onClick={onOpenData}>{t("Открыть данные →")}</button>}</div>
      <DataTable rows={rows} columns={schema.objects.flatMap((object) => object.fields.map((field) => field.name))} label={t(context === "source" ? "Таблица первых строк" : "Данные результата")} />
    </section>}
    {hasCharts && <div className="dashboard-section-heading dashboard-charts-heading"><div><h3>{t("Что видно в данных")}</h3><span className="dashboard-scope-badge">{t(context === "source" ? "По предпросмотру" : "По результату")}</span></div><button type="button" onClick={() => setShowPalette((open) => !open)} aria-expanded={showPalette}>{t("Цвета графиков")}</button></div>}
    {hasCharts || missingColumns.length > 0 ? <div className="dashboard-grid">
      {model.timeline && <ChartCard title={`${t("Динамика по полю ")}${model.timeline.field}`} unit={t("строки")}><LineChart values={model.timeline.values} color={primary} gradient={gradient} label={`${t("Динамика по полю ")}${model.timeline.field}`} /><p className="visually-hidden">{model.timeline.values.map((point) => `${point.label}: ${numberText(point.value)}`).join("; ")}</p></ChartCard>}
      {model.category && <ChartCard title={`${t("Частые значения: ")}${model.category.field}`} unit={t("строки")}><HorizontalBars values={model.category.values} color={model.timeline ? secondary : primary} label={`${t("Частые значения поля ")}${model.category.field}`} /></ChartCard>}
      {model.numeric && <ChartCard title={`${t("Распределение: ")}${model.numeric.field}`} unit={t("строки")} detailLabel={`${t("Детали распределения ")}${model.numeric.field}`} detail={<>
        <h4>{t("Статистика распределения")}</h4>
        <dl className="chart-detail-stats">
          <div><dt>{t("Минимум")}</dt><dd>{numberText(model.numeric.min)}</dd></div>
          <div><dt>{t("Максимум")}</dt><dd>{numberText(model.numeric.max)}</dd></div>
          <div><dt>{t("Среднее")}</dt><dd>{numberText(Number(model.numeric.mean.toFixed(2)))}</dd></div>
          <div><dt>{t("Медиана")}</dt><dd>{numberText(median)}</dd></div>
          <div><dt>{t("Стандартное отклонение")}</dt><dd>{numberText(Number(standardDeviation.toFixed(2)))}</dd></div>
        </dl>
      </>} footer={<><h4>{t("Пропуски по столбцам")}</h4>{missingColumns.length ? <MissingBars values={missingColumns} color={secondary} /> : <p>{t(profile ? "В профиле пропусков нет" : "Профиль источника ещё не загружен")}</p>}</>}><Histogram values={model.numeric.histogram} color={seriesColor(model.numeric.field, colors)} field={model.numeric.field} /><div className="numeric-summary"><span>{t("Мин.")} <b>{model.numeric.min.toLocaleString(locale === "en" ? "en-US" : "ru-RU")}</b></span><span>{t("Среднее")} <b>{model.numeric.mean.toLocaleString(locale === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 2 })}</b></span><span>{t("Макс.")} <b>{model.numeric.max.toLocaleString(locale === "en" ? "en-US" : "ru-RU")}</b></span></div></ChartCard>}
      {missingColumns.length > 0 && <ChartCard title={t("Пропуски по столбцам")} unit={t("доля")}><MissingBars values={missingColumns} color={secondary} /></ChartCard>}
    </div> : <div className="dashboard-empty">{t("Для графиков нужны числовые, текстовые или временные поля.")}</div>}
  </div>;
}
