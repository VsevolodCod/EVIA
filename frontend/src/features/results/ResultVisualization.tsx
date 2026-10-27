import { useMemo, useState } from "react";
import type { Row } from "../../api";
import { DataTable } from "./DataTable";
import "./resultVisualization.css";

type Point = { label: string; value: number };
type ChartData = { labelField: string; valueField: string; points: Point[] };
type View = "table" | "bar" | "line";

function numberValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim().replace(",", ".");
  if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function chartData(rows: Row[]): ChartData | null {
  const fields = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const valueField = fields.find((field) => rows.some((row) => numberValue(row[field]) !== null));
  if (!valueField) return null;
  const labelField = fields.find((field) => field !== valueField && rows.some((row) => row[field] !== null && row[field] !== undefined && row[field] !== ""));
  if (!labelField) return null;
  const points = rows.flatMap((row) => {
    const value = numberValue(row[valueField]);
    const label = row[labelField];
    return value === null || label === null || label === undefined || label === "" ? [] : [{ label: String(label), value }];
  });
  return points.length ? { labelField, valueField, points } : null;
}

function ResultChart({ data, type }: { data: ChartData; type: "bar" | "line" }) {
  const width = 640; const height = 235; const left = 48; const right = 18; const top = 20; const bottom = 48;
  const maximum = Math.max(...data.points.map((point) => point.value), 1);
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const x = (index: number) => left + plotWidth * ((index + .5) / data.points.length);
  const y = (value: number) => top + plotHeight * (1 - value / maximum);
  const points = data.points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const visible = data.points.slice(0, 12);
  const description = type === "bar" ? `Столбчатый график: ${data.valueField} по ${data.labelField}` : `Линейный график: ${data.valueField} по ${data.labelField}`;
  return <div className="result-chart" role="img" aria-label={description}>
    <div className="result-chart-meta">{data.labelField} → {data.valueField}</div>
    <svg viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {[0, .5, 1].map((step) => <line key={step} x1={left} x2={width - right} y1={y(maximum * step)} y2={y(maximum * step)} />)}
      {[0, .5, 1].map((step) => <text key={step} x={left - 8} y={y(maximum * step) + 3} textAnchor="end">{Math.round(maximum * step).toLocaleString("ru-RU")}</text>)}
      {type === "bar" ? visible.map((point, index) => {
        const barWidth = Math.max(10, Math.min(40, plotWidth / data.points.length - 8));
        return <g key={`${point.label}-${index}`}><rect x={x(index) - barWidth / 2} y={y(point.value)} width={barWidth} height={top + plotHeight - y(point.value)} rx="3" /><title>{`${point.label}: ${point.value.toLocaleString("ru-RU")}`}</title><text x={x(index)} y={height - 19} textAnchor="middle">{point.label}</text></g>;
      }) : <><polyline points={points} fill="none" /><>{visible.map((point, index) => <g key={`${point.label}-${index}`}><circle cx={x(index)} cy={y(point.value)} r="4" /><title>{`${point.label}: ${point.value.toLocaleString("ru-RU")}`}</title><text x={x(index)} y={height - 19} textAnchor="middle">{point.label}</text></g>)}</></>}
    </svg>
  </div>;
}

export function ResultVisualization({
  rows,
  label,
  copyableIdentifierColumns,
}: {
  rows: Row[];
  label: string;
  copyableIdentifierColumns?: readonly string[];
}) {
  const data = useMemo(() => chartData(rows), [rows]);
  const [view, setView] = useState<View>("table");
  const select = (next: View) => setView(next);
  return <div className="result-visualization">
    {data ? <nav className="result-view-toggle" aria-label="Представление результата">
      <button aria-pressed={view === "table"} onClick={() => select("table")}>Таблица</button>
      <button aria-pressed={view === "bar"} onClick={() => select("bar")}>Столбцы</button>
      <button aria-pressed={view === "line"} onClick={() => select("line")}>Линия</button>
    </nav> : <p className="result-visualization-note">Для графика нужен числовой показатель и поле для подписей.</p>}
    {view === "table" || !data ? <DataTable rows={rows} label={label} copyableIdentifierColumns={copyableIdentifierColumns} /> : <ResultChart data={data} type={view} />}
  </div>;
}
