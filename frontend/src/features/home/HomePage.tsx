import type { ReactNode } from "react";
import type { ChatSummary, Source } from "../../api";
import { ErrorNotice, Icon } from "../../components";
import { useLanguage } from "../../i18n";

type Props = {
  sources: Source[];
  selectedSourceId: string | null;
  chats: ChatSummary[];
  chatLoading: boolean;
  chatError: string;
  loading: boolean;
  error: string;
  uploadCard: ReactNode;
  onRefresh: () => void;
  onSelectSource: (id: string) => void;
  onPostgres: () => void;
  onReports: () => void;
  onOpenChat: (chat: ChatSummary) => void;
  onRefreshChats: () => void;
};

export function HomePage({
  sources, selectedSourceId, chats, chatLoading, chatError, loading, error, uploadCard, onRefresh,
  onSelectSource, onPostgres, onReports, onOpenChat, onRefreshChats,
}: Props) {
  const { t } = useLanguage();
  return (
    <div className="home-page">
      <header className="home-hero">
        <h1>{t("Данные")}</h1>
      </header>
      <div className={`home-content-grid ${chats.length || chatLoading || chatError ? "has-recent-chats" : ""}`}>
        <div className="home-primary-column">
          {uploadCard}
          <section className="home-section" aria-labelledby="home-sources-title">
            <div className="home-section-heading">
              <div><h2 id="home-sources-title">{t("Источники данных")}</h2><span>{sources.length} {t("подключено")}</span></div>
              <button className="icon-button" aria-label={t("Обновить источники")} onClick={onRefresh} disabled={loading}>
                <Icon name="refresh" size={17} />
              </button>
            </div>
            {error && <ErrorNotice message={error} onRetry={onRefresh} />}
            {loading ? <p className="home-empty" role="status">{t("Загружаем источники…")}</p> : sources.length ? (
              <div className="home-source-grid">
                {sources.map((source) => (
                  <button className={`home-source-card ${selectedSourceId === source.source_id ? "selected" : ""}`} key={source.source_id} aria-label={source.name} aria-pressed={selectedSourceId === source.source_id} onClick={() => onSelectSource(source.source_id)}>
                    <span className="home-source-icon"><Icon name="file" size={19} /></span>
                    <span className="home-source-copy"><strong>{source.name}</strong><small>{source.source_type.toUpperCase()}</small></span>
                    <Icon name="chevron" size={17} />
                  </button>
                ))}
              </div>
            ) : !error ? <div className="home-empty"><strong>{t("Пока нет подключённых источников")}</strong></div> : null}
            <div className="home-source-actions">
              <button className="postgres-nav" onClick={onPostgres}><Icon name="grid" size={16} /> {t("Подключить PostgreSQL")}</button>
              <button className="postgres-nav" onClick={onReports}><Icon name="file" size={16} /> {t("Сохранённые отчёты")}</button>
            </div>
          </section>
        </div>

        {(chats.length > 0 || chatLoading || chatError) && <aside className="home-section home-recent" aria-labelledby="home-recent-title">
          <div className="home-section-heading"><div><h2 id="home-recent-title">{t("Недавние диалоги")}</h2></div></div>
          <div className="home-recent-scroll">
            {chatError && <ErrorNotice message={chatError} onRetry={onRefreshChats} label={t("Повторить загрузку диалогов")} />}
            {chatLoading && <p className="sidebar-note" role="status">{t("Загружаем диалоги…")}</p>}
            {chats.length > 0 && <div className="home-chat-list">
              {chats.map((chat) => <button key={chat.chat_id} onClick={() => onOpenChat(chat)}>
                <span className="home-chat-icon"><Icon name="chat" size={17} /></span>
                <span><strong>{chat.title || t("Новый диалог")}</strong><small>{chat.source_id ? t("Диалог с источником") : t("Диалог без источника")}</small></span>
                <Icon name="chevron" size={16} />
              </button>)}
            </div>}
          </div>
        </aside>}
      </div>
    </div>
  );
}
