import type { Row } from "../../api";

export type ChartColumn = { name: string; data_type?: string; is_identifier_candidate?: boolean };
export type ChartPoint = { label: string; value: number | null };
export type ResultChartData = { labelField: string; valueField: string; points: ChartPoint[] };
export type PieSlice = { label: string; percent: number; value: number };

const numericTypes = new Set(["integer", "number", "decimal", "numeric", "float", "double", "real", "bigint", "smallint"]);
const identifierName = /(^|[^\p{L}\p{N}])(id|uuid|guid|code|key|код|номер|идентификатор)($|[^\p{L}\p{N}])/iu;
const missing = (value: unknown) => value === null || value === undefined || (typeof value === "string" && !value.trim());

export function chartNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim().replace(",", ".");
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

export function chartFields(rows: Row[], columns: readonly ChartColumn[] = [], identifiers: readonly string[] = []) {
  const fields = [...new Set(rows.flatMap(row => Object.keys(row)))];
  const definitions = new Map(columns.map(column => [column.name, column]));
  const measures = fields.filter(field => {
    const definition = definitions.get(field);
    const words = field.replace(/([a-z\d])([A-Z])/g, "$1_$2");
    if (identifiers.includes(field) || definition?.is_identifier_candidate || identifierName.test(words)) return false;
    const values = rows.map(row => row[field]).filter(value => !missing(value));
    if (!values.some(value => chartNumber(value) !== null)) return false;
    const type = definition?.data_type?.toLowerCase();
    // Declared string/date/boolean columns stay dimensions even when cells look numeric.
    if (type && type !== "unknown") return numericTypes.has(type);
    // Legacy untyped results must not turn padded codes into measurements.
    return values.every(value => chartNumber(value) !== null &&
      !(typeof value === "string" && /^[+-]?0\d/.test(value.trim())));
  });
  return { fields, measures };
}

export function resultChartData(rows: Row[], valueField: string, labelField: string): ResultChartData {
  return {
    valueField, labelField,
    // Preserve row order, duplicate labels and gaps; never aggregate in the renderer.
    points: rows.map(row => ({
      label: missing(row[labelField]) ? "Нет подписи" : String(row[labelField]),
      value: chartNumber(row[valueField]),
    })),
  };
}

export function chartDomain(points: ChartPoint[]) {
  let minimum = 0; let maximum = 0;
  for (const point of points) {
    if (point.value !== null) {
      minimum = Math.min(minimum, point.value);
      maximum = Math.max(maximum, point.value);
    }
  }
  if (minimum === maximum) maximum = 1;
  return { minimum, maximum };
}

export function pieChartData(points: ChartPoint[]): PieSlice[] | null {
  // A negative value makes the meaning of a slice ambiguous. Missing values
  // are omitted from the proportion, never silently treated as zero.
  if (points.some((point) => point.value !== null && point.value < 0)) return null;
  const positive = points.filter((point): point is { label: string; value: number } =>
    point.value !== null && point.value > 0);
  if (!positive.length) return null;
  const maximum = Math.max(...positive.map((point) => point.value));
  // Scaling first avoids overflowing the sum for very large finite values.
  const grouped = new Map<string, { value: number; weight: number }>();
  for (const point of positive) {
    const previous = grouped.get(point.label) ?? { value: 0, weight: 0 };
    grouped.set(point.label, {
      value: previous.value + point.value,
      weight: previous.weight + point.value / maximum,
    });
  }
  const sorted = [...grouped].map(([label, value]) => ({ label, ...value }))
    .sort((left, right) => right.weight - left.weight || left.label.localeCompare(right.label, "ru"));
  const visible = sorted.length > 8
    ? [...sorted.slice(0, 7), {
      label: "Остальные", value: sorted.slice(7).reduce((total, slice) => total + slice.value, 0),
      weight: sorted.slice(7).reduce((total, slice) => total + slice.weight, 0),
    }]
    : sorted;
  const totalWeight = sorted.reduce((total, slice) => total + slice.weight, 0);
  return visible.map(({ label, value, weight }) => ({ label, value, percent: weight / totalWeight * 100 }));
}
