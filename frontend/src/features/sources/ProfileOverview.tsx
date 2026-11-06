import type { CSSProperties } from "react";
import type { Profile } from "../../api";
import { Icon } from "../../components/Icon";
import { useLanguage } from "../../i18n";
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
  const { t } = useLanguage();
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <span className="analytics-kicker">{t("ДАННЫЕ В ФОКУСЕ")}</span>
          <h2>{t("Обзор данных")}</h2>
        </div>
        <span className="analytics-badge">
          <Icon name="check" size={14} /> {t("Профиль рассчитан")}
        </span>
      </div>
      {profile.sample_size === 0 && (
        <p className="analytics-notice">{t("В выборке нет строк")}</p>
      )}
      {model.profiledCount < model.fields.length && (
        <p className="analytics-notice">
          {t("Профиль доступен для")} {model.profiledCount} {t("из")} {model.fields.length} {t("столбцов. Показатели рассчитаны только по ним.")}
        </p>
      )}
      <div className="analytics-grid">
        <section
          className="insight-card completeness-card"
          aria-label={t("Заполненность выборки")}
        >
          <h3>{t("Заполненность")}</h3>
          <p className="analytics-caption">{t("Ячейки в выборке")}</p>
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
                <small>{t("заполнено")}</small>
              </div>
            </div>
            <dl className="chart-legend">
              <div>
                <dt>
                  <i className="legend-dot" />{t("С данными")}
                </dt>
                <dd>{numberText(model.filled)}</dd>
              </div>
              <div>
                <dt>
                  <i className="legend-dot missing" />
                  {t("Пропуски")}
                </dt>
                <dd>{numberText(model.missing)}</dd>
              </div>
            </dl>
          </div>
          <button className="analytics-link" onClick={onQuality}>
            {t("Изучить качество")} <Icon name="chevron" size={14} />
          </button>
        </section>
        <section className="insight-card" aria-label={t("Типы столбцов")}>
          <h3>{t("Состав данных")}</h3>
          <p className="analytics-caption">{t("Типы определены по выборке")}</p>
          <div className="type-composition" aria-hidden="true">
            {model.types.map((type, i) => (
              <span
                className={`type-color-${i % 5}`}
                key={t(type.label)}
                style={{ flex: type.count }}
              />
            ))}
          </div>
          <dl className="type-legend">
            {model.types.map((type, i) => (
              <div key={type.label}>
                <dt>
                  <i className={`legend-dot type-color-${i % 5}`} />
                  {t(type.label)}
                </dt>
                <dd>
                  {numberText(type.count)} <span>{t("столб.")}</span>
                </dd>
              </div>
            ))}
          </dl>
          {!model.fields.length && (
            <p className="analytics-caption">{t("В источнике нет столбцов.")}</p>
          )}
        </section>
      </div>
      <section
        className="insight-card attention-card"
        aria-label={t("На что обратить внимание")}
      >
        <div className="analytics-card-heading">
          <h3>{t("На что обратить внимание")}</h3>
          <span className="count-badge">{model.missingFields.length}</span>
        </div>
        {model.missingFields.length ? (
          <div className="attention-list">
            {model.missingFields.slice(0, 3).map((field) => (
              <button
                key={field.name}
                onClick={() => onColumn(field.name)}
                aria-label={`${t("Изучить")} ${field.name}`}
              >
                <span className="attention-symbol" aria-hidden="true">
                  !
                </span>
                <span>
                  <strong>{field.name}</strong>
                  <small>
                    {numberText(field.stats!.sample_null_count)} {t("пропусков в выборке")}
                  </small>
                </span>
                <Icon name="chevron" size={15} />
              </button>
            ))}
          </div>
        ) : (
          <p className="analytics-caption">
            {model.completeness === null
              ? t("Для проверки пропусков нужны строки с данными.")
              : t("В доступном профиле пропусков нет. Это не проверка дубликатов или корректности значений.")}
          </p>
        )}
        {model.missingFields.length > 3 && (
          <button className="analytics-link" onClick={onQuality}>
            {t("Все столбцы с пропусками")} <Icon name="chevron" size={14} />
          </button>
        )}
      </section>
      <section className="insight-card" aria-label={t("Краткий обзор столбцов")}>
        <div className="analytics-card-heading">
          <h3>{t("Ваши столбцы")}</h3>
          <button className="analytics-link" onClick={onColumns}>
            {t("Все")} {model.fields.length} <Icon name="chevron" size={14} />
          </button>
        </div>
        <div className="column-shortlist">
          {model.fields.slice(0, 6).map((field) => (
            <button key={field.name} onClick={() => onColumn(field.name)}>
              <span>
                <strong>{field.name}</strong>
                <small>{t(typeLabel(field.type))}</small>
              </span>
              <span className="column-unique">
                {field.stats
                  ? numberText(field.stats.distinct_sample_values)
                  : "—"}
                <small>{t("уникальных")}</small>
              </span>
              <Icon name="chevron" size={14} />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
