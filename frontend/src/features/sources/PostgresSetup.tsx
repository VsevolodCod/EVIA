import type { PostgresStatus, Source } from "../../api";
import { ErrorNotice, Icon } from "../../components";
import { useLanguage } from "../../i18n";
import "./postgresSetup.css";

export function PostgresSetup({
  status,
  loading,
  error,
  sources,
  onRetry,
  onSelect,
}: {
  status: PostgresStatus | null;
  loading: boolean;
  error: string;
  sources: Source[];
  onRetry: () => void;
  onSelect: (sourceId: string) => void;
}) {
  const { t } = useLanguage();
  if (loading && !status)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ")}</span>
        <h1>{t("Проверяем PostgreSQL…")}</h1>
        <p>{t("Проверяем безопасное подключение сервиса к базе данных.")}</p>
      </section>
    );

  if (error)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ")}</span>
        <h1>{t("Не удалось проверить PostgreSQL")}</h1>
        <ErrorNotice message={t(error)} onRetry={onRetry} label={t("Проверить снова")} />
      </section>
    );

  if (!status?.configured)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ")}</span>
        <h1>{t("Подключите PostgreSQL")}</h1>
        <p>
          {t("EVIA получает доступ к базе через защищённые переменные сервиса. Пароль не вводится в браузере и не сохраняется в ссылках или хранилище страницы.")}
        </p>
        <ol className="postgres-steps">
          <li><code>POSTGRES_DSN</code> — {t("строка подключения с read-only пользователем.")}</li>
          <li><code>POSTGRES_ALLOWED_TABLES</code> — {t("разрешённые таблицы через запятую, например")} <code>public.orders</code>.</li>
          <li>{t("Перезапустите сервис и нажмите «Проверить снова».")}</li>
        </ol>
        <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? t("Проверяем…") : t("Проверить снова")}
        </button>
      </section>
    );

  if (!status.connected)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ")}</span>
        <h1>{t("PostgreSQL пока недоступен")}</h1>
        <p>
          {t("Настройки найдены, но сервис не смог установить безопасное соединение. Проверьте доступность базы и read-only пользователя, затем повторите проверку.")}
        </p>
        <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? t("Проверяем…") : t("Повторить проверку")}
        </button>
      </section>
    );

  return (
    <section className="postgres-setup" aria-label={t("Подключение PostgreSQL")}>
      <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ")}</span>
      <div className="postgres-setup__heading">
        <div>
          <h1>{t("PostgreSQL подключён")}</h1>
          <p>{t("Выберите разрешённую таблицу — она сразу станет доступна в аналитике и чате.")}</p>
        </div>
        <span className="postgres-status"><span aria-hidden="true" />{t("Связь есть")}</span>
      </div>
      {sources.length ? (
        <div className="postgres-source-list" aria-label={t("Разрешённые таблицы PostgreSQL")}>
          {sources.map((source) => (
            <button key={source.source_id} onClick={() => onSelect(source.source_id)} aria-label={`${t("Выбрать")} ${source.name}`}>
              <span className="postgres-source-list__icon"><Icon name="grid" size={18} /></span>
              <span><strong>{source.name}</strong><small>POSTGRESQL · только чтение</small></span>
              <Icon name="chevron" size={18} />
            </button>
          ))}
        </div>
      ) : (
        <div className="postgres-empty-tables">
          <strong>{t("Разрешённые таблицы не найдены")}</strong>
          <p>{t("Проверьте значение")} <code>POSTGRES_ALLOWED_TABLES</code>, {t("затем обновите список.")}</p>
        </div>
      )}
      <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
        <Icon name="refresh" size={16} />
        {loading ? "Обновляем…" : "Обновить подключение"}
      </button>
    </section>
  );
}
