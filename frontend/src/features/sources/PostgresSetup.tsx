import type { PostgresStatus, Source } from "../../api";
import { ErrorNotice, Icon } from "../../components";
import { useLanguage } from "../../language";
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
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL", "PostgreSQL connection")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ", "DATA SOURCE")}</span>
        <h1>{t("Проверяем PostgreSQL…", "Checking PostgreSQL…")}</h1>
        <p>{t("Проверяем безопасное подключение сервиса к базе данных.", "Checking the service's secure database connection.")}</p>
      </section>
    );

  if (error)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL", "PostgreSQL connection")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ", "DATA SOURCE")}</span>
        <h1>{t("Не удалось проверить PostgreSQL", "Could not check PostgreSQL")}</h1>
        <ErrorNotice message={error} onRetry={onRetry} label={t("Проверить снова", "Check again")} />
      </section>
    );

  if (!status?.configured)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL", "PostgreSQL connection")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ", "DATA SOURCE")}</span>
        <h1>{t("Подключите PostgreSQL", "Connect PostgreSQL")}</h1>
        <p>
          {t("EVIA получает доступ к базе через защищённые переменные сервиса. Пароль не вводится в браузере и не сохраняется в ссылках или хранилище страницы.", "EVIA accesses the database through protected service variables. The password is not entered in the browser or stored in links or browser storage.")}
        </p>
        <ol className="postgres-steps">
          <li><code>POSTGRES_DSN</code> — {t("строка подключения с read-only пользователем.", "connection string for a read-only user.")}</li>
          <li><code>POSTGRES_ALLOWED_TABLES</code> — {t("разрешённые таблицы через запятую, например", "comma-separated allowed tables, for example")} <code>public.orders</code>.</li>
          <li>{t("Перезапустите сервис и нажмите «Проверить снова».", "Restart the service and select Check again.")}</li>
        </ol>
        <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? t("Проверяем…", "Checking…") : t("Проверить снова", "Check again")}
        </button>
      </section>
    );

  if (!status.connected)
    return (
      <section className="postgres-setup" aria-label={t("Подключение PostgreSQL", "PostgreSQL connection")}>
        <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ", "DATA SOURCE")}</span>
        <h1>{t("PostgreSQL пока недоступен", "PostgreSQL is unavailable")}</h1>
        <p>
          {t("Настройки найдены, но сервис не смог установить безопасное соединение. Проверьте доступность базы и read-only пользователя, затем повторите проверку.", "Configuration was found, but the service could not establish a secure connection. Check database availability and the read-only user, then retry.")}
        </p>
        <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? t("Проверяем…", "Checking…") : t("Повторить проверку", "Retry check")}
        </button>
      </section>
    );

  return (
    <section className="postgres-setup" aria-label={t("Подключение PostgreSQL", "PostgreSQL connection")}>
      <span className="postgres-setup__eyebrow">{t("ИСТОЧНИК ДАННЫХ", "DATA SOURCE")}</span>
      <div className="postgres-setup__heading">
        <div>
          <h1>{t("PostgreSQL подключён", "PostgreSQL connected")}</h1>
          <p>{t("Выберите разрешённую таблицу — она сразу станет доступна в аналитике и чате.", "Select an allowed table to use it in analytics and chat.")}</p>
        </div>
        <span className="postgres-status"><span aria-hidden="true" />{t("Связь есть", "Connected")}</span>
      </div>
      {sources.length ? (
        <div className="postgres-source-list" aria-label={t("Разрешённые таблицы PostgreSQL", "Allowed PostgreSQL tables")}>
          {sources.map((source) => (
            <button key={source.source_id} onClick={() => onSelect(source.source_id)} aria-label={t(`Выбрать ${source.name}`, `Select ${source.name}`)}>
              <span className="postgres-source-list__icon"><Icon name="grid" size={18} /></span>
              <span><strong>{source.name}</strong><small>POSTGRESQL · {t("только чтение", "read-only")}</small></span>
              <Icon name="chevron" size={18} />
            </button>
          ))}
        </div>
      ) : (
        <div className="postgres-empty-tables">
          <strong>{t("Разрешённые таблицы не найдены", "No allowed tables found")}</strong>
          <p>{t("Проверьте значение", "Check")} <code>POSTGRES_ALLOWED_TABLES</code>, {t("затем обновите список.", "then refresh the list.")}</p>
        </div>
      )}
      <button className="postgres-setup__action" onClick={onRetry} disabled={loading}>
        <Icon name="refresh" size={16} />
        {loading ? t("Обновляем…", "Refreshing…") : t("Обновить подключение", "Refresh connection")}
      </button>
    </section>
  );
}
