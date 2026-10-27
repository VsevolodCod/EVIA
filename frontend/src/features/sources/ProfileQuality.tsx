import { Icon } from "../../components/Icon";
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
  return (
    <div className="analytics-section">
      <div className="analytics-title">
        <div>
          <h2>Качество данных</h2>
        </div>
      </div>
      <div className="quality-summary">
        <div>
          <strong>{numberText(model.missing)}</strong>
          <span>пустых ячеек</span>
        </div>
        <div>
          <strong>{numberText(model.missingFields.length)}</strong>
          <span>столбцов с пропусками</span>
        </div>
        <div>
          <strong>{numberText(model.profiledCount)}</strong>
          <span>столбцов в профиле</span>
        </div>
      </div>
      {!model.missingFields.length ? (
        <div className="analytics-empty">
          <Icon name="check" size={26} />
          <h3>
            {model.completeness === null
              ? "Недостаточно данных для проверки"
              : "Пропусков в профиле нет"}
          </h3>
          <p>
            Дубликаты, выбросы и связи между столбцами этим профилем не
            проверяются.
          </p>
        </div>
      ) : (
        <section className="insight-card" aria-label="Пропуски по столбцам">
          <h3>Где не хватает данных</h3>
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
                  aria-label={`Изучить ${field.name}`}
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
          Для {model.fields.length - model.profiledCount} столбцов статистика
          недоступна.
        </p>
      )}
    </div>
  );
}
