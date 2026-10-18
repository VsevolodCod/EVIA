import type { CSSProperties } from "react";
import type { Profile } from "../../api";
import { Icon } from "../../components/Icon";
import {
  numberText,
  percentText,
  typeLabel,
  type ProfileModel,
} from "./profileModel";

export function ProfileOverview({
  model,
  profile,
  onColumn,
  onQuality,
  onColumns,
}: {
  model: ProfileModel;
  profile: Profile;
  onColumn: (name: string) => void;
  onQuality: () => void;
  onColumns: () => void;
}) {
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <span className="analytics-kicker">ДАННЫЕ В ФОКУСЕ</span>
          <h2>Обзор данных</h2>
        </div>
        <span className="analytics-badge">
          <Icon name="check" size={14} /> Профиль рассчитан
        </span>
      </div>
      {profile.sample_size === 0 && (
        <p className="analytics-notice">В выборке нет строк</p>
      )}
      {model.profiledCount < model.fields.length && (
        <p className="analytics-notice">
          Профиль доступен для {model.profiledCount} из {model.fields.length}{" "}
          столбцов. Показатели рассчитаны только по ним.
        </p>
      )}
      <div className="analytics-grid">
        <section
          className="insight-card completeness-card"
          aria-label="Заполненность выборки"
        >
          <h3>Заполненность</h3>
          <p className="analytics-caption">Ячейки в выборке</p>
          <div className="completeness-body">
            <div
              className="completeness-ring"
              style={
                {
                  "--completion": `${model.completeness ?? 0}%`,
                } as CSSProperties
              }
            >
              <div>
                <strong>{percentText(model.completeness)}</strong>
                <small>заполнено</small>
              </div>
            </div>
            <dl className="chart-legend">
              <div>
                <dt>
                  <i className="legend-dot" />С данными
                </dt>
                <dd>{numberText(model.filled)}</dd>
              </div>
              <div>
                <dt>
                  <i className="legend-dot missing" />
                  Пропуски
                </dt>
                <dd>{numberText(model.missing)}</dd>
              </div>
            </dl>
          </div>
          <button className="analytics-link" onClick={onQuality}>
            Изучить качество <Icon name="chevron" size={14} />
          </button>
        </section>
        <section className="insight-card" aria-label="Типы столбцов">
          <h3>Состав данных</h3>
          <p className="analytics-caption">Типы определены по выборке</p>
          <div className="type-composition" aria-hidden="true">
            {model.types.map((type, i) => (
              <span
                className={`type-color-${i % 5}`}
                key={type.label}
                style={{ flex: type.count }}
              />
            ))}
          </div>
          <dl className="type-legend">
            {model.types.map((type, i) => (
              <div key={type.label}>
                <dt>
                  <i className={`legend-dot type-color-${i % 5}`} />
                  {type.label}
                </dt>
                <dd>
                  {numberText(type.count)} <span>столб.</span>
                </dd>
              </div>
            ))}
          </dl>
          {!model.fields.length && (
            <p className="analytics-caption">В источнике нет столбцов.</p>
          )}
        </section>
      </div>
      <section
        className="insight-card attention-card"
        aria-label="На что обратить внимание"
      >
        <div className="analytics-card-heading">
          <h3>На что обратить внимание</h3>
          <span className="count-badge">{model.missingFields.length}</span>
        </div>
        {model.missingFields.length ? (
          <div className="attention-list">
            {model.missingFields.slice(0, 3).map((field) => (
              <button
                key={field.name}
                onClick={() => onColumn(field.name)}
                aria-label={`Изучить ${field.name}`}
              >
                <span className="attention-symbol" aria-hidden="true">
                  !
                </span>
                <span>
                  <strong>{field.name}</strong>
                  <small>
                    {numberText(field.stats!.sample_null_count)} пропусков в
                    выборке
                  </small>
                </span>
                <Icon name="chevron" size={15} />
              </button>
            ))}
          </div>
        ) : (
          <p className="analytics-caption">
            {model.completeness === null
              ? "Для проверки пропусков нужны строки с данными."
              : "В доступном профиле пропусков нет. Это не проверка дубликатов или корректности значений."}
          </p>
        )}
        {model.missingFields.length > 3 && (
          <button className="analytics-link" onClick={onQuality}>
            Все столбцы с пропусками <Icon name="chevron" size={14} />
          </button>
        )}
      </section>
      <section className="insight-card" aria-label="Краткий обзор столбцов">
        <div className="analytics-card-heading">
          <h3>Ваши столбцы</h3>
          <button className="analytics-link" onClick={onColumns}>
            Все {model.fields.length} <Icon name="chevron" size={14} />
          </button>
        </div>
        <div className="column-shortlist">
          {model.fields.slice(0, 6).map((field) => (
            <button key={field.name} onClick={() => onColumn(field.name)}>
              <span className="column-type-icon" aria-hidden="true">
                {field.type === "string"
                  ? "Aa"
                  : field.type === "boolean"
                    ? "✓"
                    : "#"}
              </span>
              <span>
                <strong>{field.name}</strong>
                <small>{typeLabel(field.type)}</small>
              </span>
              <span className="column-unique">
                {field.stats
                  ? numberText(field.stats.distinct_sample_values)
                  : "—"}
                <small>уникальных</small>
              </span>
              <Icon name="chevron" size={14} />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
