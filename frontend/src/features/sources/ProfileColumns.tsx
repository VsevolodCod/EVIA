import { useState } from "react";
import {
  numberText,
  percentText,
  ratio,
  hasExactStats,
  rowsText,
  typeLabel,
  type ProfileField,
} from "./profileModel";

export function ProfileColumns({
  fields,
  sampleSize,
  candidateGrainKeys = [],
  initialSearch = "",
}: {
  fields: ProfileField[];
  sampleSize: number;
  candidateGrainKeys?: string[][];
  initialSearch?: string;
}) {
  const [search, setSearch] = useState(initialSearch);
  const [onlyMissing, setOnlyMissing] = useState(false);
  const filtered = fields.filter(
    (field) =>
      field.name
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()) &&
      (!onlyMissing || (field.stats && hasExactStats(field.stats)
        ? field.stats.null_count > 0
        : (field.stats?.sample_null_count ?? 0) > 0)),
  );
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <h2>Столбцы данных</h2>
        </div>
        <span className="count-badge">
          {filtered.length} / {fields.length}
        </span>
      </div>
      <div className="column-toolbar">
        <label className="column-search">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            aria-label="Поиск столбца"
            placeholder="Найти столбец…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <button
          className="filter-chip"
          aria-pressed={onlyMissing}
          onClick={() => setOnlyMissing(!onlyMissing)}
        >
          С пропусками
        </button>
      </div>
      {candidateGrainKeys.length > 0 && (
        <aside className="profile-grain-candidates" aria-label="Гипотезы о ключе строк">
          <h3>Гипотезы о ключе строк</h3>
          <ul>
            {candidateGrainKeys.map((fields) => <li key={fields.join("\u0000")}>{fields.join(" + ")}</li>)}
          </ul>
          <p>Комбинация уникальна в текущем снимке и требует проверки бизнес-смысла.</p>
        </aside>
      )}
      {!filtered.length && (
        <div className="analytics-empty">
          <h3>Столбцы не найдены</h3>
          <p>Попробуйте другое название или уберите фильтр.</p>
          <button
            className="analytics-link"
            onClick={() => {
              setSearch("");
              setOnlyMissing(false);
            }}
          >
            Сбросить поиск
          </button>
        </div>
      )}
      <div className="column-cards">
        {filtered.map((field) => (
          <ColumnCard
            key={field.name}
            field={field}
            sampleSize={sampleSize}
            initialOpen={Boolean(initialSearch)}
          />
        ))}
      </div>
    </div>
  );
}

function ColumnCard({
  field,
  sampleSize,
  initialOpen,
}: {
  field: ProfileField;
  sampleSize: number;
  initialOpen: boolean;
}) {
  const stats = field.stats;
  const exact = stats && hasExactStats(stats);
  const total = stats
    ? exact
      ? stats.non_null_count + stats.null_count
      : stats.sample_non_null_count + stats.sample_null_count
    : 0;
  const maximum = Math.max(
    1,
    ...(stats?.top_values.map((value) => value.count) ?? []),
  );
  return (
    <section className="column-card" aria-label={`Столбец ${field.name}`}>
      <details open={initialOpen || undefined}>
        <summary>
          <span className={`column-type-icon column-type-${field.type.replaceAll(" ", "-")}`} aria-hidden="true">
            {field.type === "string" ? "Aa" : field.type.includes("date") || field.type.includes("time") ? "▣" : "#"}
          </span>
          <span className="column-card-title">
            <strong>{field.name}</strong>
            <small>
              {typeLabel(field.type)}
            {field.identifier ? " · Гипотеза: кандидат в идентификаторы" : ""}
            </small>
          </span>
          <span
            className={`column-status ${stats && (exact ? stats.null_count : stats.sample_null_count) ? "has-missing" : ""}`}
          >
            {stats ? percentText(ratio(exact ? stats.null_count : stats.sample_null_count, total)) : "Нет профиля"}
          </span>
        </summary>
        {stats ? (
          <div className="column-details">
            {exact ? <>
              <dl className="column-stats column-stats-exact">
                <div><dt>Заполнено</dt><dd>{numberText(stats.non_null_count)}</dd></div>
                <div><dt>NULL</dt><dd>{numberText(stats.null_count)}</dd></div>
                <div><dt>Пустые строки</dt><dd>{numberText(stats.empty_count)}</dd></div>
                <div><dt>Уникальных значений</dt><dd>{numberText(stats.distinct_count)}</dd></div>
                <div><dt>Уникальность</dt><dd>{percentText(stats.uniqueness_ratio * 100)}</dd></div>
              </dl>
              {(stats.numeric || stats.temporal) && <dl className="column-ranges">
                {stats.numeric && <div><dt>Диапазон чисел</dt><dd>{stats.numeric.minimum} — {stats.numeric.maximum}</dd></div>}
                {stats.temporal && <div><dt>Диапазон дат</dt><dd>{stats.temporal.minimum} — {stats.temporal.maximum}</dd></div>}
              </dl>}
            </> : <dl className="column-stats">
              <div><dt>Заполнено</dt><dd>{numberText(stats.sample_non_null_count)}</dd></div>
              <div><dt>Пропуски</dt><dd>{numberText(stats.sample_null_count)}</dd></div>
              <div><dt>Доля пропусков</dt><dd>{percentText(ratio(stats.sample_null_count, total))}</dd></div>
            </dl>}
            <div className="frequency-heading">
              <h4>{exact ? "Частые значения — только по выборке" : "Частые значения"}</h4>
              <span>{exact ? `${rowsText(sampleSize)} в выборке` : "Количество в выборке"}</span>
            </div>
            {stats.top_values.length ? (
              <ul
                className="frequency-chart"
                aria-label={`Частоты ${field.name}`}
              >
                {stats.top_values.map((item, index) => (
                  <li key={`${item.value}-${index}`}>
                    <div className="frequency-label">
                      <span title={item.value}>{item.value}</span>
                      <b>{numberText(item.count)}</b>
                    </div>
                    <div className="frequency-track" aria-hidden="true">
                      <span
                        style={{ width: `${(item.count / maximum) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="analytics-caption">Нет заполненных значений</p>
            )}
            <p className="chart-footnote">
              Показаны самые частые значения из выборки, а не все значения
              столбца.
            </p>
          </div>
        ) : null}
      </details>
      {!stats && (
        <p className="analytics-caption column-unavailable">
          Статистика столбца недоступна
        </p>
      )}
    </section>
  );
}
