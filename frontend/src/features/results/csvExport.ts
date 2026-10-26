/** Only returned table cells enter the download; query metadata stays on the server/UI. */
export type CsvTable = { columns: string[]; rows: unknown[][]; truncated: boolean };

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function csvTableFrom(data: unknown): CsvTable | null {
  if (Array.isArray(data)) {
    if (!data.every(record)) return null;
    const columns = [...new Set(data.flatMap((row) => Object.keys(row)))];
    return columns.length ? {
      columns,
      rows: data.map((row) => columns.map((column) => row[column] ?? null)),
      truncated: false,
    } : null;
  }
  if (!record(data) || !Array.isArray(data.columns) || !Array.isArray(data.rows)) return null;
  const columns = data.columns.map((column) => record(column) ? column.name : null);
  if (!columns.length || columns.some((name) => typeof name !== "string") ||
      !data.rows.every((row) => Array.isArray(row) && row.length === columns.length)) return null;
  return {
    columns: columns as string[],
    rows: data.rows as unknown[][],
    truncated: data.truncated === true,
  };
}

function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? ""
    : typeof value === "object" ? JSON.stringify(value) : String(value);
  // Spreadsheet programs can interpret strings as formulas even when a CSV
  // field is quoted. Prefix dangerous string cells, including column names.
  if (typeof value === "string" && /^[\u0000-\u0020\uFEFF]*[=+\-@]/u.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function serializeCsv(table: CsvTable): string {
  return "\uFEFF" + [table.columns, ...table.rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\r\n") + "\r\n";
}

export function downloadCsv(table: CsvTable): void {
  const blob = new Blob([serializeCsv(table)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "evia-result.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
