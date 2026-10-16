import { Icon } from "./Icon";

export function ErrorNotice({
  message,
  onRetry,
  label = "Повторить",
}: {
  message: string;
  onRetry?: () => void;
  label?: string;
}) {
  return (
    <div className="error-notice" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          <Icon name="refresh" />
          {label}
        </button>
      )}
    </div>
  );
}
