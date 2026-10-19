import type { Row, SourceSchema } from "../../api";

export type ChartValue = { label: string; value: number };
export type NumericSummary = {
  field: string;
  mean: number;
  min: number;
  max: number;
  values: number[];
  histogram: ChartValue[];
};
export type DashboardModel = {
  rowCount: number;
  columnCount: number;
  completeness: number | null;
  numeric: NumericSummary | null;
  category: { field: string; values: ChartValue[] } | null;
  timeline: { field: string; values: ChartValue[] } | null;
};

const numericTypes = new Set(["number", "integer", "float"]);
const dateTypes = new Set(["date", "datetime"]);
const isMissing = (value: unknown) =>
  value === null || value === undefined || value === "";

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value: number) {
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function histogram(values: number[]): ChartValue[] {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ label: formatNumber(min), value: values.length }];
  const bucketCount = Math.min(8, Math.max(3, Math.ceil(Math.sqrt(values.length))));
  const width = (max - min) / bucketCount;
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    label: `${formatNumber(min + index * width)}–${formatNumber(min + (index + 1) * width)}`,
    value: 0,
  }));
  values.forEach((value) => {
    const index = Math.min(bucketCount - 1, Math.floor((value - min) / width));
    buckets[index].value += 1;
  });
  return buckets;
}

function formatDate(date: Date) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

export function buildDashboardModel(schema: SourceSchema, rows: Row[]): DashboardModel {
  const fields = schema.objects.flatMap((object) => object.fields);
  const columnCount = fields.length;
  const totalCells = rows.length * columnCount;
  const presentCells = rows.reduce(
    (total, row) =>
      total + fields.filter((field) => !isMissing(row[field.name])).length,
    0,
  );
  const completeness = totalCells ? (presentCells / totalCells) * 100 : null;
  const analyticalFields = fields.filter((field) => !field.is_identifier_candidate);

  const numericField = analyticalFields.find((field) => numericTypes.has(field.inferred_type));
  const numericValues = numericField
    ? rows.map((row) => asNumber(row[numericField.name])).filter((value): value is number => value !== null)
    : [];
  const numeric = numericField && numericValues.length
    ? {
        field: numericField.name,
        mean: numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length,
        min: Math.min(...numericValues),
        max: Math.max(...numericValues),
        values: numericValues,
        histogram: histogram(numericValues),
      }
    : null;

  const categoryField = analyticalFields.find((field) => field.inferred_type === "string");
  const category = categoryField
    ? (() => {
        const counts = new Map<string, number>();
        rows.forEach((row) => {
          const value = row[categoryField.name];
          if (isMissing(value)) return;
          const label = String(value);
          counts.set(label, (counts.get(label) ?? 0) + 1);
        });
        const values = [...counts]
          .map(([label, value]) => ({ label, value }))
          .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label, "ru"))
          .slice(0, 8);
        return values.length ? { field: categoryField.name, values } : null;
      })()
    : null;

  const dateField = analyticalFields.find((field) => dateTypes.has(field.inferred_type));
  const timeline = dateField
    ? (() => {
        const counts = new Map<number, number>();
        rows.forEach((row) => {
          const value = row[dateField.name];
          if (typeof value !== "string" && !(value instanceof Date)) return;
          const date = new Date(value);
          if (Number.isNaN(date.getTime())) return;
          const key = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
          counts.set(key, (counts.get(key) ?? 0) + 1);
        });
        const values = [...counts]
          .sort(([left], [right]) => left - right)
          .slice(-24)
          .map(([time, value]) => ({ label: formatDate(new Date(time)), value }));
        return values.length ? { field: dateField.name, values } : null;
      })()
    : null;

  return { rowCount: rows.length, columnCount, completeness, numeric, category, timeline };
}
