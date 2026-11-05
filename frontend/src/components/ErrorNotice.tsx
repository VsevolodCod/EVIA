import { Icon } from "./Icon";
import { useLanguage } from "../i18n";

export function ErrorNotice({
  message,
  onRetry,
  label = "Повторить",
}: {
  message: string;
  onRetry?: () => void;
  label?: string;
}) {
  const { t } = useLanguage();
  return (
    <div className="error-notice" role="alert">
      <p>{t(message)}</p>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          <Icon name="refresh" />
          {t(label)}
        </button>
      )}
    </div>
  );
}
