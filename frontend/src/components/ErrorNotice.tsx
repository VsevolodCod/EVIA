import { Icon } from "./Icon";
import { useLanguage } from "../language";

export function ErrorNotice({
  message,
  onRetry,
  label,
}: {
  message: string;
  onRetry?: () => void;
  label?: string;
}) {
  const { t } = useLanguage();
  return (
    <div className="error-notice" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          <Icon name="refresh" />
          {label ?? t("Повторить", "Retry")}
        </button>
      )}
    </div>
  );
}
