import { useMemo, useState } from "react";
import type { Row } from "../../api";
import { EviaMascot } from "../../components/EviaMascot";

export function valueText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

const PAGE_SIZE = 25;

export function DataTable({
  rows,
  columns,
  label = "Таблица данных",
}: {
  rows: Row[];
  columns?: string[];
  label?: string;
}) {
  const [position, setPosition] = useState({ rows, page: 0 });
  const fields = useMemo(
    () => columns ?? [...new Set(rows.flatMap((row) => Object.keys(row)))],
    [columns, rows],
  );
  const lastPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  // A result change resets the page synchronously; no stale table is painted.
  const page = position.rows === rows ? Math.min(position.page, lastPage) : 0;
  const start = page * PAGE_SIZE;
  const visibleRows = rows.slice(start, start + PAGE_SIZE);

  if (!rows.length)
    return (
      <div className="empty-table">
        <EviaMascot state="empty_table" size={80} decorative />
        <p>Нет строк для отображения</p>
        <span>
          Результат пуст. Это не означает нулевое значение показателя.
        </span>
      </div>
    );
  if (!fields.length) return <p className="muted">Строки не содержат полей.</p>;

  return (
    <div className="data-table">
      <div
        className="table-scroll"
        role="region"
        aria-label={label}
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th scope="col" className="row-number">
                №
              </th>
              {fields.map((field) => (
                <th scope="col" key={field}>
                  {field}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={start + index}>
                <td className="row-number">{start + index + 1}</td>
                {fields.map((field) => (
                  <td key={field}>{valueText(row[field])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > PAGE_SIZE && (
        <div className="pagination" aria-label={`Страницы: ${label}`}>
          <span aria-live="polite">
            {start + 1}–{Math.min(start + PAGE_SIZE, rows.length)} из{" "}
            {rows.length.toLocaleString("ru-RU")}
          </span>
          <div>
            <button
              disabled={page === 0}
              aria-label="Предыдущие строки"
              onClick={() => setPosition({ rows, page: page - 1 })}
            >
              ← Назад
            </button>
            <button
              disabled={page === lastPage}
              aria-label="Следующие строки"
              onClick={() => setPosition({ rows, page: page + 1 })}
            >
              Далее →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
