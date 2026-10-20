import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  waitForChat,
  errorMessage,
  type ChatMessage,
  type ChatSummary,
  type PostgresStatus,
  type Source,
} from "./api";
import { ErrorNotice, Evia, Icon, SafeMarkdown } from "./components";
import { SourceInspector } from "./features/sources/SourceInspector";
import { PostgresSetup } from "./features/sources/PostgresSetup";
import type { Entry, View } from "./features/chat/types";
import { ResponseTiming } from "./features/chat/ResponseTiming";
import "./styles.css";
import {
  resolveEviaState,
  errorEviaState,
  eviaStatus,
} from "./features/mascot/resolveEviaState";
import type { EviaState } from "./features/mascot/states";

const CHAT_SOURCE_STORAGE_KEY = "evia.chat-sources.v1";

type ChatPage = {
  hasMore: boolean;
  nextBefore: number | null;
  loading: boolean;
  error: string;
};

function savedChatSources(): Record<string, string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(CHAT_SOURCE_STORAGE_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] =>
        typeof entry[0] === "string" && typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

function entriesFromMessages(chatId: string, messages: ChatMessage[]): Entry[] {
  const entries: Entry[] = [];
  let user: ChatMessage | undefined;
  for (const message of messages) {
    if (message.role === "user") {
      user = message;
      continue;
    }
    if (message.role === "assistant" && user) {
      entries.push({
        id: user.message_id,
        conversationId: chatId,
        question: user.content,
        state: "success",
        answer: { answer: message.content, steps: 0, tool_results: [] },
      });
      user = undefined;
    }
  }
  if (user) {
    entries.push({
      id: user.message_id,
      conversationId: chatId,
      question: user.content,
      state: "error",
      mascotState: "warning",
      error: "Ответ для этого вопроса не сохранился. Повторите запрос.",
    });
  }
  return entries;
}

function mergeEntries(existing: Entry[], loaded: Entry[]): Entry[] {
  const known = new Set(existing.map((entry) => entry.id));
  return [...loaded.filter((entry) => !known.has(entry.id)), ...existing];
}

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState("");
  const [postgresStatus, setPostgresStatus] = useState<PostgresStatus | null>(null);
  const [postgresLoading, setPostgresLoading] = useState(false);
  const [postgresError, setPostgresError] = useState("");
  const [sourceSetup, setSourceSetup] = useState<"csv" | "postgres">("csv");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [histories, setHistories] = useState<Record<string, Entry[]>>({});
  const [chatSummaries, setChatSummaries] = useState<ChatSummary[]>([]);
  const [chatSources, setChatSources] = useState<Record<string, string>>(savedChatSources);
  const [historyPages, setHistoryPages] = useState<Record<string, ChatPage>>({});
  const [historyListLoading, setHistoryListLoading] = useState(true);
  const [historyListError, setHistoryListError] = useState("");
  const [activeIds, setActiveIds] = useState<
    Record<string, string | undefined>
  >({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [view, setView] = useState<View>("overview");
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const [uploadFailure, setUploadFailure] = useState<EviaState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const sourceController = useRef<AbortController | null>(null);
  const postgresController = useRef<AbortController | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const askControllers = useRef(new Map<string, AbortController>());
  const historyControllers = useRef(new Map<string, AbortController>());
  const activeConversations = useRef(new Map<string, string>());
  const pendingChats = useRef(new Map<string, Promise<string>>());
  const loadedChats = useRef(new Set<string>());
  const sequence = useRef(0);
  const mounted = useRef(true);
  const source = sources.find((item) => item.source_id === selectedId);
  const postgresSources = sources.filter((item) => item.source_type === "postgresql");
  const history = selectedId ? (histories[selectedId] ?? []) : [];
  const activeEntry = history.find(
    (entry) => entry.id === (selectedId ? activeIds[selectedId] : undefined),
  );
  const conversationEntries = activeEntry
    ? history.filter((entry) => entry.conversationId === activeEntry.conversationId)
    : [];
  const conversations = history.filter((entry, index) =>
    history.findIndex((item) => item.conversationId === entry.conversationId) === index);
  const selectedServerChats = selectedId
    ? chatSummaries.filter((chat) => chatSources[chat.chat_id] === selectedId)
    : [];
  const failedServerChat = selectedServerChats.find(
    (chat) => historyPages[chat.chat_id]?.error,
  );
  const activeConversationId = activeEntry?.conversationId;
  const activePage = activeConversationId ? historyPages[activeConversationId] : undefined;
  const pending = conversationEntries.find((entry) => entry.state === "pending");
  const draft = selectedId ? (drafts[selectedId] ?? "") : "";
  const mascotState = resolveEviaState({
    uploading,
    uploadFailure,
    request: pending ? (pending.mascotState ?? "thinking") : undefined,
    connectionFailure: Boolean(sourcesError),
    selectedId,
    uploadedId,
    draft,
    entry: activeEntry,
  });
  async function loadSources() {
    sourceController.current?.abort();
    const controller = new AbortController();
    sourceController.current = controller;
    setSourcesLoading(true);
    setSourcesError("");
    try {
      const list = await api.sources(controller.signal);
      if (!controller.signal.aborted) {
        setSources(list);
        setSelectedId((id) =>
          list.some((item) => item.source_id === id) ? id : null,
        );
      }
    } catch (error) {
      if (!controller.signal.aborted) setSourcesError(errorMessage(error));
    } finally {
      if (!controller.signal.aborted) setSourcesLoading(false);
    }
  }
  async function loadPostgresStatus() {
    postgresController.current?.abort();
    const controller = new AbortController();
    postgresController.current = controller;
    setPostgresLoading(true);
    setPostgresError("");
    try {
      const status = await api.postgresStatus(controller.signal);
      if (!controller.signal.aborted) setPostgresStatus(status);
    } catch (error) {
      if (!controller.signal.aborted) setPostgresError(errorMessage(error));
    } finally {
      if (!controller.signal.aborted) setPostgresLoading(false);
    }
  }
  async function refreshPostgres() {
    await Promise.all([loadPostgresStatus(), loadSources()]);
  }
  async function loadChatList() {
    setHistoryListLoading(true);
    setHistoryListError("");
    try {
      const list = await api.chats();
      if (mounted.current) setChatSummaries(list);
    } catch (error) {
      if (mounted.current) setHistoryListError(errorMessage(error));
    } finally {
      if (mounted.current) setHistoryListLoading(false);
    }
  }
  function rememberChatSource(chatId: string, sourceId: string) {
    setChatSources((previous) => {
      const next = { ...previous, [chatId]: sourceId };
      try {
        localStorage.setItem(CHAT_SOURCE_STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* The chat remains available for this session if browser storage is unavailable. */
      }
      return next;
    });
  }
  function forgetChatSource(chatId: string) {
    setChatSources((previous) => {
      if (!(chatId in previous)) return previous;
      const { [chatId]: _removed, ...next } = previous;
      try {
        localStorage.setItem(CHAT_SOURCE_STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* The stale association stays removed for this session. */
      }
      return next;
    });
    setHistoryPages((previous) => {
      const { [chatId]: _removed, ...next } = previous;
      return next;
    });
    loadedChats.current.delete(chatId);
  }
  async function loadChatHistory(sourceId: string, chatId: string, before?: number) {
    const requestKey = `${chatId}:${before ?? "latest"}`;
    if (historyControllers.current.has(requestKey)) return;
    const controller = new AbortController();
    historyControllers.current.set(requestKey, controller);
    setHistoryPages((previous) => ({
      ...previous,
      [chatId]: {
        hasMore: previous[chatId]?.hasMore ?? false,
        nextBefore: previous[chatId]?.nextBefore ?? null,
        loading: true,
        error: "",
      },
    }));
    try {
      const page = await api.chatHistory(chatId, before, controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      const entries = entriesFromMessages(chatId, page.messages);
      setHistories((previous) => ({
        ...previous,
        [sourceId]: before
          ? mergeEntries(previous[sourceId] ?? [], entries)
          : [
              ...(previous[sourceId] ?? []).filter((entry) => entry.conversationId !== chatId),
              ...entries,
            ],
      }));
      setHistoryPages((previous) => ({
        ...previous,
        [chatId]: {
          hasMore: page.has_more,
          nextBefore: page.next_before,
          loading: false,
          error: "",
        },
      }));
      loadedChats.current.add(chatId);
    } catch (error) {
      if (!controller.signal.aborted && mounted.current) {
        if (error instanceof ApiError && error.status === 404) {
          forgetChatSource(chatId);
          return;
        }
        setHistoryPages((previous) => ({
          ...previous,
          [chatId]: {
            hasMore: previous[chatId]?.hasMore ?? false,
            nextBefore: previous[chatId]?.nextBefore ?? null,
            loading: false,
            error: errorMessage(error),
          },
        }));
      }
    } finally {
      historyControllers.current.delete(requestKey);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void loadSources();
    void loadChatList();
    return () => {
      mounted.current = false;
      sourceController.current?.abort();
      postgresController.current?.abort();
      uploadController.current?.abort();
      askControllers.current.forEach((controller) => controller.abort());
      historyControllers.current.forEach((controller) => controller.abort());
    };
  }, []);

  useEffect(() => {
    if (!selectedId || historyListLoading) return;
    chatSummaries
      .filter((chat) => chatSources[chat.chat_id] === selectedId)
      .forEach((chat) => {
        if (!loadedChats.current.has(chat.chat_id))
          void loadChatHistory(selectedId, chat.chat_id);
      });
  }, [selectedId, chatSummaries, chatSources, historyListLoading]);

  function selectSource(id: string) {
    setSelectedId(id);
    setSourceSetup("csv");
    setUploadFailure(null);
    setUploadError("");
    setView("overview");
  }
  function changeDraft(value: string) {
    if (selectedId)
      setDrafts((previous) => ({ ...previous, [selectedId]: value }));
  }
  function newAnalysis() {
    if (selectedId) {
      setActiveIds((previous) => ({ ...previous, [selectedId]: undefined }));
      activeConversations.current.delete(selectedId);
      setDrafts((previous) => ({ ...previous, [selectedId]: "" }));
    }

    setSelectedId(null);
    setUploadedId(null);
    setUploadFailure(null);
    setUploadError("");
    setFailedFile(null);
    setDragOver(false);
    setSourceSetup("csv");
    setView("overview");
  }
  function openPostgresSetup() {
    setSelectedId(null);
    setSourceSetup("postgres");
    void loadPostgresStatus();
  }
  async function upload(file: File) {
    if (uploading) return;
    setUploadError("");
    setUploadFailure(null);
    setFailedFile(null);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadFailure("invalid_csv");
      setUploadError("Поддерживаются только файлы .csv.");
      return;
    }
    if (file.size === 0) {
      setUploadFailure("invalid_csv");
      setUploadError("Файл пуст. Выберите CSV с заголовком и данными.");
      return;
    }
    setUploading(true);
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const created = await api.upload(file, controller.signal);
      if (controller.signal.aborted) return;
      sourceController.current?.abort();
      setSourcesLoading(false);
      setSourcesError("");
      setSources((previous) => [
        created,
        ...previous.filter((item) => item.source_id !== created.source_id),
      ]);
      selectSource(created.source_id);
      setUploadedId(created.source_id);
    } catch (error) {
      if (!controller.signal.aborted) {
        setUploadError(errorMessage(error));
        setUploadFailure(errorEviaState(error, true));
        setFailedFile(file);
      }
    } finally {
      if (!controller.signal.aborted) setUploading(false);
    }
  }
  async function send(question: string, retryId?: string) {
    if (
      !selectedId ||
      !question.trim() ||
      question.trim().length > 4000
    )
      return;
    setUploadFailure(null);
    setUploadError("");
    const sourceId = selectedId;
    const retried = retryId ? histories[sourceId]?.find((item) => item.id === retryId) : undefined;
    const conversationId = retried?.conversationId ?? activeConversations.current.get(sourceId) ?? crypto.randomUUID();
    if (askControllers.current.has(conversationId)) return;
    activeConversations.current.set(sourceId, conversationId);
    const id = retryId ?? `question-${++sequence.current}`;
    const entry: Entry = {
      id,
      conversationId,
      question: question.trim(),
      state: "pending",
      startedAt: performance.now(),
      mascotState: retryId ? "retrying" : "thinking",
    };
    const controller = new AbortController();
    askControllers.current.set(conversationId, controller);
    setHistories((previous) => ({
      ...previous,
      [sourceId]: retryId
        ? (previous[sourceId] ?? []).map((item) =>
            item.id === id ? entry : item,
          )
        : [...(previous[sourceId] ?? []), entry],
    }));
    setActiveIds((previous) => ({ ...previous, [sourceId]: id }));
    if (!retryId) setDrafts((previous) => ({ ...previous, [sourceId]: "" }));
    const finish = (update: Partial<Entry>) => {
      const elapsedMs = performance.now() - entry.startedAt!;
      if (mounted.current)
        setHistories((previous) => ({
          ...previous,
          [sourceId]: (previous[sourceId] ?? []).map((item) =>
            item.id === id ? { ...item, ...update, elapsedMs } : item,
          ),
        }));
    };
    try {
      // Create once before asking, so an LLM failure/abort cannot lose chat_id.
      // Let creation finish even if waiting is cancelled; reuse it on retry.
      let chat = pendingChats.current.get(conversationId);
      if (!chat) {
        chat = api.createChat(entry.question.slice(0, 200)).then((result) => {
          rememberChatSource(result.chat_id, sourceId);
          setChatSummaries((previous) => [
            result,
            ...previous.filter((item) => item.chat_id !== result.chat_id),
          ]);
          return result.chat_id;
        });
        pendingChats.current.set(conversationId, chat);
        chat.catch(() => pendingChats.current.delete(conversationId));
      }
      const chatId = await waitForChat(chat, controller.signal);
      controller.signal.throwIfAborted();
      const answer = await api.chat(entry.question, sourceId, chatId, controller.signal);
      if (controller.signal.aborted)
        finish({
          state: "error",
          mascotState: "cancelled",
          error: "Ожидание остановлено. Сервер может продолжать обработку.",
        });
      else finish({ state: "success", answer });
    } catch (error) {
      finish({
        state: "error",
        mascotState: controller.signal.aborted
          ? "cancelled"
          : errorEviaState(error),
        error: controller.signal.aborted
          ? "Ожидание остановлено. Сервер может продолжать обработку."
          : errorMessage(error),
      });
    } finally {
      askControllers.current.delete(conversationId);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }
  function chooseFile() {
    fileInput.current?.click();
  }

  return (
    <div className="app">
      <a className="skip-link" href="#analysis">
        Перейти к данным
      </a>
      <header className="topbar">
        <a
          className="brand"
          href="#analysis"
          aria-label="EVIA, рабочее пространство"
        >
          EVIA
        </a>
      </header>
      <div className="workspace">
        <aside className="sidebar" aria-label="Навигация рабочего пространства">
          <button className="primary new-analysis" onClick={newAnalysis}>
            <Icon name="plus" />
            Новый анализ
          </button>
          <section className="nav-section">
            <div className="nav-heading">
              <h2>Источники</h2>
              <button
                className="icon-button"
                aria-label="Обновить источники"
                onClick={() => void loadSources()}
                disabled={sourcesLoading}
              >
                <Icon name="refresh" size={15} />
              </button>
            </div>
            {sourcesLoading && (
              <p className="sidebar-note" role="status">
                Загружаем источники…
              </p>
            )}
            {sourcesError && (
              <ErrorNotice
                message={sourcesError}
                onRetry={() => void loadSources()}
              />
            )}
            {!sourcesLoading && !sourcesError && !sources.length && (
              <p className="sidebar-note">Нет источников</p>
            )}
            <div className="source-list">
              {sources.map((item) => (
                <button
                  className={`nav-item ${selectedId === item.source_id ? "selected" : ""}`}
                  aria-label={item.name}
                  aria-pressed={selectedId === item.source_id}
                  key={item.source_id}
                  onClick={() => selectSource(item.source_id)}
                >
                  <span className="source-icon">
                    <Icon name="file" />
                  </span>
                  <span className="source-title">
                    {item.name}
                    <small>{item.source_type.toUpperCase()}</small>
                  </span>
                  {selectedId === item.source_id && (
                    <span className="selection-dot" />
                  )}
                </button>
              ))}
            </div>
            <button
              className="upload-nav"
              onClick={chooseFile}
              title="CSV · UTF-8 · запятая или точка с запятой"
              disabled={uploading}
            >
              <Icon name="plus" size={16} />
              {uploading ? "Загружаем CSV…" : "Добавить CSV"}
            </button>
            <button
              className="postgres-nav"
              onClick={openPostgresSetup}
              aria-pressed={!source && sourceSetup === "postgres"}
            >
              <Icon name="grid" size={16} />
              Подключить PostgreSQL
              {postgresStatus?.connected && <span aria-label="PostgreSQL доступен" />}
            </button>
            <input
              className="visually-hidden"
              type="file"
              accept=".csv,text/csv"
              aria-label="Загрузить CSV"
              ref={fileInput}
              tabIndex={-1}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
            {uploadError && (
              <ErrorNotice
                message={uploadError}
                onRetry={
                  failedFile ? () => void upload(failedFile) : chooseFile
                }
                label={failedFile ? "Повторить загрузку CSV" : "Выбрать файл"}
              />
            )}
          </section>
          <section className="nav-section history-section">
            <div className="nav-heading">
              <h2>История</h2>
              {conversations.length > 0 && (
                <span className="nav-count">{conversations.length}</span>
              )}
            </div>
            {historyListLoading ? (
              <p className="sidebar-note" role="status">Загружаем диалоги…</p>
            ) : historyListError ? (
              <ErrorNotice
                message={historyListError}
                onRetry={() => void loadChatList()}
                label="Повторить загрузку диалогов"
              />
            ) : failedServerChat && !history.length ? (
              <ErrorNotice
                message={historyPages[failedServerChat.chat_id]?.error ?? "Не удалось загрузить историю."}
                onRetry={() => selectedId && void loadChatHistory(selectedId, failedServerChat.chat_id)}
                label="Повторить загрузку истории"
              />
            ) : history.length ? (
              <div className="history-list">
                {[...conversations].reverse().map((entry) => (
                  <button
                    key={entry.id}
                    className={`history-item ${activeEntry?.conversationId === entry.conversationId ? "active" : ""}`}
                    aria-label={entry.question}
                    title={entry.question}
                    aria-pressed={activeEntry?.conversationId === entry.conversationId}
                    onClick={() => {
                      if (selectedId) {
                        activeConversations.current.set(selectedId, entry.conversationId!);
                        setActiveIds((previous) => ({
                          ...previous,
                          [selectedId]: history.filter((item) => item.conversationId === entry.conversationId).at(-1)?.id,
                        }));
                      }
                      setView("results");
                    }}
                  >
                    <Icon name="chat" size={16} />
                    <span>{entry.question}</span>
                    {history.some((item) => item.conversationId === entry.conversationId && item.state === "pending") && (
                      <span className="pending-dot" />
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <p className="sidebar-note">Нет диалогов</p>
            )}
          </section>
        </aside>
        <main
          className={`analysis ${source ? "" : "analysis-empty"}`}
          id="analysis"
          tabIndex={-1}
        >
          {source ? (
            <SourceInspector
              source={source}
              entry={activeEntry}
              view={view}
              setView={setView}
            />
          ) : sourceSetup === "postgres" ? (
            <PostgresSetup
              status={postgresStatus}
              loading={postgresLoading}
              error={postgresError}
              sources={postgresSources}
              onRetry={() => void refreshPostgres()}
              onSelect={selectSource}
            />
          ) : (
            <>
              <section
                className={`upload-card ${dragOver ? "drag-over" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragOver(false);
                  const file = event.dataTransfer.files[0];
                  if (file) void upload(file);
                }}
                aria-label="Добавление источника"
              >
                <div className="upload-illustration" aria-hidden="true">
                  <div className="paper-sheet paper-back" />
                  <div className="paper-sheet">
                    <span className="csv-label">CSV</span>
                    <div className="paper-grid">
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </div>
                  </div>
                  <span className="paper-plus">+</span>
                </div>
                <h1>{uploading ? "Загрузка CSV…" : "Добавьте CSV"}</h1>
                <p>Перетащите файл сюда</p>
                <button
                  className="primary"
                  onClick={chooseFile}
                  disabled={uploading}
                >
                  <Icon name="upload" />
                  {uploading ? "Загружаем…" : "Выбрать CSV"}
                </button>
                <small>UTF-8 · запятая или ; · первая строка — заголовки</small>
              </section>
            </>
          )}
        </main>
        <aside className="chat-panel" aria-label="Чат с EVIA">
          <header className="chat-header">
            <h2>Чат</h2>
            <span
              className="chat-status"
              aria-label={pending ? "Обрабатывает вопрос" : "Ожидает вопроса"}
            />
          </header>
          <div className="chat-content">
            {activeEntry ? (
              <>
              {activePage?.hasMore && (
                <div className="history-pagination">
                  {activePage.loading ? (
                    <p role="status">Загружаем предыдущие сообщения…</p>
                  ) : activePage.error ? (
                    <ErrorNotice
                      message={activePage.error}
                      onRetry={() => selectedId && activePage.nextBefore !== null && void loadChatHistory(selectedId, activeConversationId!, activePage.nextBefore)}
                      label="Повторить загрузку истории"
                    />
                  ) : (
                    <button
                      className="text-button"
                      onClick={() => selectedId && activePage.nextBefore !== null && void loadChatHistory(selectedId, activeConversationId!, activePage.nextBefore)}
                    >
                      Показать предыдущие сообщения
                    </button>
                  )}
                </div>
              )}
              {conversationEntries.map((message) => <article key={message.id} className="chat-turn">
                <div className="user-message">{message.question}</div>
                <section className="assistant-message" aria-label="Ответ EVIA">
                  <div className="reply-label">EVIA</div>
                  {message.state === "pending" ? (
                    <div className="thinking" role="status">
                      <span />
                      <span />
                      <span />
                      <p>Изучаю ваш вопрос…</p>
                    </div>
                  ) : message.state === "error" ? (
                    <ErrorNotice
                      message={
                        message.error ?? "Не удалось получить ответ."
                      }
                      onRetry={() =>
                        void send(message.question, message.id)
                      }
                      label="Повторить вопрос"
                    />
                  ) : (
                    <>
                      <SafeMarkdown>
                        {message.answer?.answer ||
                          "Модель вернула пустой ответ."}
                      </SafeMarkdown>
                      <button
                        className="result-link"
                        onClick={() => {
                          if (selectedId) setActiveIds((previous) => ({ ...previous, [selectedId]: message.id }));
                          setView("results");
                        }}
                      >
                        <Icon name="grid" />
                        Результаты инструментов
                        <Icon name="chevron" size={15} />
                      </button>
                    </>
                  )}
                  <ResponseTiming key={`${message.id}-${message.startedAt}`} entry={message} />
                </section>
              </article>)}
              </>
            ) : (
              <div className="chat-welcome">
                <Evia large state={mascotState} />
                <p
                  className={`evia-live-status ${["welcome", "waiting", "listening", "explaining"].includes(mascotState) ? "visually-hidden" : ""}`}
                  role="status"
                >
                  {eviaStatus(mascotState)}
                </p>
                {source && (
                  <div className="suggestions">
                    {[
                      "Какие есть столбцы?",
                      "Покажи первые строки",
                      "Есть ли пропуски?",
                    ].map((question) => (
                      <button
                        key={question}
                        onClick={() => {
                          changeDraft(question);
                          composer.current?.focus();
                        }}
                      >
                        {question}
                        <Icon name="chevron" size={14} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="chat-bottom">
            {activeEntry && (
              <div className="helper">
                <Evia state={mascotState} />
                <div role="status">
                  <strong>{eviaStatus(mascotState)}</strong>
                </div>
              </div>
            )}
            <form className="composer" onSubmit={submit}>
              <label className="visually-hidden" htmlFor="question">
                Ваш вопрос
              </label>
              <textarea
                id="question"
                ref={composer}
                placeholder={
                  source
                    ? "Что хотите узнать о данных?"
                    : "Сначала добавьте источник…"
                }
                rows={3}
                value={draft}
                maxLength={4000}
                disabled={!source}
                onChange={(event) => changeDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    (event.ctrlKey || event.metaKey) &&
                    event.key === "Enter"
                  ) {
                    event.preventDefault();
                    void send(draft);
                  }
                }}
              />
              <div className="composer-footer">
                <span title={source?.name}>
                  {source ? (
                    <>
                      <span className="status-dot" />
                      {source.name}
                    </>
                  ) : (
                    "Источник не выбран"
                  )}
                </span>
                {pending ? (
                  <button
                    type="button"
                    className="stop-button"
                    aria-label="Прекратить ожидание"
                    onClick={() => {
                      if (pending?.conversationId)
                        askControllers.current.get(pending.conversationId)?.abort();
                    }}
                  >
                    <Icon name="close" />
                  </button>
                ) : (
                  <button
                    className="send-button"
                    type="submit"
                    aria-label="Отправить вопрос"
                    disabled={
                      !source || !draft.trim() || draft.trim().length > 4000
                    }
                  >
                    <Icon name="arrow" />
                  </button>
                )}
              </div>
            </form>
            <div className="composer-hint">
              <span>Ctrl / ⌘ + Enter — отправить</span>
              {draft.length > 3500 && <span>{draft.length}/4000</span>}
            </div>
            <details className="chat-help">
              <summary>О чате</summary>
              <p>
                Вопросы продолжают выбранный диалог: модель получает предыдущие
                сообщения. «Новый анализ» открывает экран добавления источника. У каждого
                источника своя история. Сообщения сохраняются на сервере;
                список диалогов этой вкладки пока доступен до обновления страницы.
              </p>
            </details>
          </div>
        </aside>
      </div>
    </div>
  );
}
