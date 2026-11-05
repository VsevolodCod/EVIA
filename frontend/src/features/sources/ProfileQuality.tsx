import { Icon } from "../../components/Icon";
import { useLanguage } from "../../i18n";
import {
  numberText,
  percentText,
  ratio,
  hasExactStats,
  type ProfileModel,
} from "./profileModel";

export function ProfileQuality({
  model,
  onColumn,
}: {
  model: ProfileModel;
  onColumn: (name: string) => void;
}) {
  const { t } = useLanguage();
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <h2>{t("Качество данных")}</h2>
        </div>
      </div>
      <div className="quality-summary">
        <div>
          <strong>{numberText(model.missing)}</strong>
          <span>{t("пустых ячеек")}</span>
        </div>
        <div>
          <strong>{numberText(model.missingFields.length)}</strong>
          <span>{t("столбцов с пропусками")}</span>
        </div>
        <div>
          <strong>{numberText(model.profiledCount)}</strong>
          <span>{t("столбцов в профиле")}</span>
        </div>
      </div>
      {!model.missingFields.length ? (
        <div className="analytics-empty">
          <Icon name="check" size={26} />
          <h3>
            {model.completeness === null
              ? t("Недостаточно данных для проверки")
              : t("Пропусков в профиле нет")}
          </h3>
          <p>
            {t("Дубликаты, выбросы и связи между столбцами этим профилем не проверяются.")}
          </p>
        </div>
      ) : (
        <section className="insight-card" aria-label={t("Пропуски по столбцам")}>
          <h3>{t("Где не хватает данных")}</h3>
          <div className="missing-columns">
            {model.missingFields.map((field) => {
              const stats = field.stats!;
              const exact = hasExactStats(stats);
              const missingCount = exact ? stats.null_count : stats.sample_null_count;
              const missing = ratio(
                missingCount,
                exact
                  ? stats.null_count + stats.non_null_count
                  : stats.sample_null_count + stats.sample_non_null_count,
              );
              return (
                <button
                  key={field.name}
                  aria-label={`${t("Изучить")} ${field.name}`}
                  onClick={() => onColumn(field.name)}
                >
                  <span className="missing-row">
                    <strong>{field.name}</strong>
                    <span>
                      {numberText(missingCount)} ·{" "}
                      {percentText(missing)}
                    </span>
                    <Icon name="chevron" size={14} />
                  </span>
                  <span className="missing-track" aria-hidden="true">
                    <span style={{ width: `${missing ?? 0}%` }} />
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}
      {model.profiledCount < model.fields.length && (
        <p className="analytics-notice">
          {t("Для некоторых столбцов статистика недоступна.")}
        </p>
      )}
    </div>
  );
}
