import { useState } from "react";
import {
  numberText,
  percentText,
  ratio,
  typeLabel,
  type ProfileField,
} from "./profileModel";

export function ProfileColumns({
  fields,
  initialSearch = "",
}: {
  fields: ProfileField[];
  initialSearch?: string;
}) {
  const [search, setSearch] = useState(initialSearch);
  const [onlyMissing, setOnlyMissing] = useState(false);
  const filtered = fields.filter(
    (field) =>
      field.name
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()) &&
      (!onlyMissing || (field.stats?.sample_null_count ?? 0) > 0),
  );
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <span className="analytics-kicker">ИССЛЕДУЙТЕ ДЕТАЛИ</span>
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
      <p className="analytics-caption">
        Частоты и уникальные значения — по выборке. Нажмите на столбец, чтобы
        раскрыть детали.
      </p>
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
            initialOpen={Boolean(initialSearch)}
          />
        ))}
      </div>
    </div>
  );
}

function ColumnCard({
  field,
  initialOpen,
}: {
  field: ProfileField;
  initialOpen: boolean;
}) {
  const stats = field.stats;
  const total = stats
    ? stats.sample_non_null_count + stats.sample_null_count
    : 0;
  const maximum = Math.max(
    1,
    ...(stats?.top_values.map((value) => value.count) ?? []),
  );
  return (
    <section className="column-card" aria-label={`Столбец ${field.name}`}>
      <details open={initialOpen || undefined}>
        <summary>
          <span className="column-type-icon" aria-hidden="true">
            {field.type === "string" ? "Aa" : "#"}
          </span>
          <span className="column-card-title">
            <strong>{field.name}</strong>
            <small>
              {typeLabel(field.type)}
              {field.identifier ? " · Кандидат в идентификаторы" : ""}
            </small>
          </span>
          <span
            className={`column-status ${stats?.sample_null_count ? "has-missing" : ""}`}
          >
            {stats
              ? `${numberText(stats.distinct_sample_values)} уникальных`
              : "Нет профиля"}
          </span>
        </summary>
        {stats ? (
          <div className="column-details">
            <dl className="column-stats">
              <div>
                <dt>Заполнено</dt>
                <dd>{numberText(stats.sample_non_null_count)}</dd>
              </div>
              <div>
                <dt>Пропуски</dt>
                <dd>{numberText(stats.sample_null_count)}</dd>
              </div>
              <div>
                <dt>Доля пропусков</dt>
                <dd>{percentText(ratio(stats.sample_null_count, total))}</dd>
              </div>
            </dl>
            <div className="frequency-heading">
              <h4>Частые значения</h4>
              <span>Количество в выборке</span>
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
              Показаны самые частые значения из профиля, а не все значения
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
