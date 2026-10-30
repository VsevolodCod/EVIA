import { useMemo, useState } from "react";
import type { Row } from "../../api";
import { DataTable } from "./DataTable";
import { chartDomain, chartFields, pieChartData, resultChartData, type ChartColumn, type ResultChartData, type PieSlice } from "./resultChartModel";
import "./resultVisualization.css";

type View = "table" | "bar" | "line" | "pie";
const PAGE_SIZE = 50;
const pieColors = ["#087c57", "#3aa984", "#70c5a6", "#b0ddc8", "#e8ae55", "#d87a6b", "#7a93cf", "#9d82ba"];

export function PieChart({ slices, label }: { slices: PieSlice[]; label: string }) {
  const circumference = 2 * Math.PI * 82;
  let offset = 0;
  return <div className="result-pie" role="img" aria-label={label}>
    <svg viewBox="0 0 220 220" aria-hidden="true">
      <circle cx="110" cy="110" r="82" fill="none" stroke="#e9f0eb" strokeWidth="34" />
      {slices.map((slice, index) => {
        const start = offset;
        offset += slice.percent / 100;
        return <circle key={`${slice.label}-${index}`} cx="110" cy="110" r="82" fill="none"
          stroke={pieColors[index]} strokeWidth="34" transform="rotate(-90 110 110)"
          strokeDasharray={`${slice.percent / 100 * circumference} ${circumference}`}
          strokeDashoffset={-start * circumference}>
          <title>{`${slice.label}: ${slice.percent.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`}</title>
        </circle>;
      })}
    </svg>
    <ul className="result-pie-legend">{slices.map((slice, index) =>
      <li key={`${slice.label}-${index}`}><i style={{ backgroundColor: pieColors[index] }} />
        <span>{slice.label}: {slice.percent.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%</span></li>)}</ul>
  </div>;
}

function ResultChart({ data, type }: { data: ResultChartData; type: "bar" | "line" }) {
  const [position, setPosition] = useState({ data, page: 0 });
  const lastPage = Math.max(0, Math.ceil(data.points.length / PAGE_SIZE) - 1);
  const page = position.data === data ? Math.min(position.page, lastPage) : 0;
  const start = page * PAGE_SIZE;
  const visible = data.points.slice(start, start + PAGE_SIZE);
  const width = 640; const height = 235; const left = 48; const right = 18; const top = 20; const bottom = 48;
  const { minimum, maximum } = chartDomain(data.points);
  // Normalize before subtracting, so large finite values do not overflow the range.
  const scale = Math.max(Math.abs(minimum), Math.abs(maximum));
  const span = maximum / scale - minimum / scale;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const x = (index: number) => left + plotWidth * ((index + .5) / visible.length);
  const y = (value: number) => top + plotHeight * ((maximum / scale - value / scale) / span);
  const baseline = y(0);
  const segments: string[][] = [];
  let segment: string[] = [];
  visible.forEach((point, index) => {
    if (point.value === null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else segment.push(`${x(index)},${y(point.value)}`);
  });
  if (segment.length) segments.push(segment);
  const missingCount = data.points.filter(point => point.value === null).length;
  const labelStride = Math.max(1, Math.ceil(visible.length / 8));
  const description = type === "bar" ? `Столбчатый график: ${data.valueField} по ${data.labelField}` : `Линейный график: ${data.valueField} по ${data.labelField}`;
  return <div className="result-chart">
    <div className="result-chart-meta">{data.labelField} → {data.valueField}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={description}>
      {[0, .5, 1].map(step => {
        const value = minimum * (1 - step) + maximum * step;
        return <g key={step}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
          <text x={left - 8} y={y(value) + 3} textAnchor="end">{value.toLocaleString("ru-RU", { maximumSignificantDigits: 4 })}</text></g>;
      })}
      <line className="result-zero-line" x1={left} x2={width - right} y1={baseline} y2={baseline} />
      {type === "line" && segments.map((points, index) => <polyline key={index} points={points.join(" ")} fill="none" />)}
      {visible.map((point, index) => {
        if (point.value === null) return null;
        const title = `${point.label}: ${point.value.toLocaleString("ru-RU")}`;
        const barWidth = Math.min(40, plotWidth / visible.length * .7);
        return <g key={start + index}>
          {type === "bar"
            ? <rect x={x(index) - barWidth / 2} y={Math.min(baseline, y(point.value))} width={barWidth}
                height={Math.abs(baseline - y(point.value))} rx="2" tabIndex={0} aria-label={title}><title>{title}</title></rect>
            : <circle cx={x(index)} cy={y(point.value)} r="4" tabIndex={0} aria-label={title}><title>{title}</title></circle>}
        </g>;
      })}
      {visible.map((point, index) => index % labelStride === 0 && <text key={start + index} x={x(index)} y={height - 19} textAnchor="middle">
        {point.label.length > 14 ? `${point.label.slice(0, 12)}…` : point.label}
      </text>)}
    </svg>
    <p className="result-chart-meta" aria-live="polite">Точки {start + 1}–{start + visible.length} из {data.points.length}. Порядок строк сохранён.</p>
    {missingCount > 0 && <p className="result-visualization-note">Пропущено значений: {missingCount} (пустые или нечисловые). Линия в этих местах прерывается.</p>}
    {lastPage > 0 && <nav className="result-chart-pages" aria-label="Страницы графика">
      <button type="button" disabled={page === 0} onClick={() => setPosition({ data, page: page - 1 })}>Предыдущие точки</button>
      <button type="button" disabled={page === lastPage} onClick={() => setPosition({ data, page: page + 1 })}>Следующие точки</button>
    </nav>}
  </div>;
}

export function ResultVisualization({ rows, label, copyableIdentifierColumns, columns, truncated = false }: {
  rows: Row[];
  label: string;
  copyableIdentifierColumns?: readonly string[];
  columns?: readonly ChartColumn[];
  truncated?: boolean;
}) {
  const { fields, measures } = useMemo(() => chartFields(rows, columns, copyableIdentifierColumns), [rows, columns, copyableIdentifierColumns]);
  const [selectedMeasure, setMeasure] = useState("");
  const [selectedLabel, setLabel] = useState("");
  const valueField = measures.includes(selectedMeasure) ? selectedMeasure : measures.length === 1 ? measures[0] : "";
  const labelFields = fields.filter(field => field !== valueField);
  const labelField = labelFields.includes(selectedLabel) ? selectedLabel : labelFields.find(field => !measures.includes(field)) ?? labelFields[0] ?? "";
  const data = useMemo(() => valueField && labelField ? resultChartData(rows, valueField, labelField) : null, [rows, valueField, labelField]);
  const pie = useMemo(() => data ? pieChartData(data.points) : null, [data]);
  const [view, setView] = useState<View>("table");
  const selectedView = view === "pie" && !pie ? "table" : view;
  return <div className="result-visualization">
    {measures.length > 0 && fields.length > 1 && <div className="result-chart-fields">
      <label>Показатель<select value={valueField} onChange={event => setMeasure(event.target.value)}>
        <option value="" disabled>Выберите показатель</option>
        {measures.map(field => <option key={field} value={field}>{field}</option>)}
      </select></label>
      <label>Подписи<select value={labelField} onChange={event => setLabel(event.target.value)}>
        {labelFields.map(field => <option key={field} value={field}>{field}</option>)}
      </select></label>
    </div>}
    {data ? <nav className="result-view-toggle" aria-label="Представление результата">
      <button type="button" aria-pressed={selectedView === "table"} onClick={() => setView("table")}>Таблица</button>
      <button type="button" aria-pressed={selectedView === "bar"} onClick={() => setView("bar")}>Столбцы</button>
      <button type="button" aria-pressed={selectedView === "line"} onClick={() => setView("line")}>Линия</button>
      {pie && <button type="button" aria-pressed={selectedView === "pie"} onClick={() => setView("pie")}>Круговая</button>}
    </nav> : <p className="result-visualization-note">{measures.length > 1 ? "Выберите показатель для графика. Идентификаторы используются только для подписей." : "Для графика нужен числовой показатель и поле для подписей."}</p>}
    {selectedView === "table" || !data ? <DataTable rows={rows} label={label} copyableIdentifierColumns={copyableIdentifierColumns} />
      : selectedView === "pie" && pie ? <><PieChart slices={pie} label={`Круговая диаграмма: ${valueField} по ${labelField}`} />
        {truncated && <p className="result-visualization-note">Доли рассчитаны только по возвращённым строкам. Результат усечён сервером.</p>}
        {data.points.some((point) => point.value === null) && <p className="result-visualization-note">Пустые и нечисловые значения не включены в доли.</p>}</>
      : <ResultChart key={`${valueField}\u0000${labelField}`} data={data} type={selectedView === "line" ? "line" : "bar"} />}
  </div>;
}
