import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  waitForChat,
  errorMessage,
  storedAnalysis,
  type ChatMessage,
  type ChatSummary,
  type PostgresStatus,
  type Source,
} from "./api";
import { ErrorNotice, Evia, Icon, SafeMarkdown } from "./components";
import { SourceInspector } from "./features/sources/SourceInspector";
import { DashboardGallery } from "./features/results/DashboardGallery";
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
      const restored = storedAnalysis(message);
      entries.push({
        id: user.message_id,
        conversationId: chatId,
        question: user.content,
        state: "success",
        answer: restored.kind === "restored"
          ? restored.answer
          : { answer: message.content, steps: 0, tool_results: [] },
        historyDetail: restored.kind === "restored" ? undefined : restored.kind,
        elapsedMs: restored.kind === "restored"
          ? restored.answer.timing?.elapsed_ms
          : undefined,
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
  const [mobilePanel, setMobilePanel] = useState<"home" | "analytics" | "chat" | "profile">("home");
  const [mobileOverlay, setMobileOverlay] = useState<"wizard" | "upload" | "settings" | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | "system">(() => {
    const saved = localStorage.getItem("evia.theme");
    return saved === "dark" || saved === "system" ? saved : "light";
  });
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [histories, setHistories] = useState<Record<string, Entry[]>>({});
  const [chatSummaries, setChatSummaries] = useState<ChatSummary[]>([]);
  const [chatSources, setChatSources] = useState<Record<string, string>>(savedChatSources);
  const [archivedChatId, setArchivedChatId] = useState<string | null>(null);
  const [historyPages, setHistoryPages] = useState<Record<string, ChatPage>>({});
  const [historyListLoading, setHistoryListLoading] = useState(true);
  const [historyListError, setHistoryListError] = useState("");
  const [activeIds, setActiveIds] = useState<
    Record<string, string | undefined>
  >({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [view, setView] = useState<View>("overview");
  const [showDashboardGallery, setShowDashboardGallery] = useState(false);
  const [attachedDashboard, setAttachedDashboard] = useState<{ id: string; title: string } | null>(null);
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const [uploadFailure, setUploadFailure] = useState<EviaState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const [selectedUploadFile, setSelectedUploadFile] = useState<File | null>(null);
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
  const archivedChat = archivedChatId
    ? chatSummaries.find((chat) => chat.chat_id === archivedChatId)
    : undefined;
  const historyKey = selectedId ?? (archivedChat ? `archive:${archivedChat.chat_id}` : null);
  const history = historyKey ? (histories[historyKey] ?? []) : [];
  const activeEntry = history.find(
    (entry) => entry.id === (historyKey ? activeIds[historyKey] : undefined),
  );
  const conversationEntries = activeEntry
    ? history.filter((entry) => entry.conversationId === activeEntry.conversationId)
    : [];
  const conversations = history.filter((entry, index) =>
    history.findIndex((item) => item.conversationId === entry.conversationId) === index);
  const selectedServerChats = selectedId
    ? chatSummaries.filter((chat) =>
      (chat.source_id ?? chatSources[chat.chat_id]) === selectedId)
    : archivedChat ? [archivedChat] : [];
  const archivedChats = chatSummaries.filter((chat) =>
    Boolean(chat.source_id) && !sources.some((source) => source.source_id === chat.source_id));
  const unboundChats = chatSummaries.filter((chat) =>
    !chat.source_id && !chatSources[chat.chat_id]);
  const historyCount = (selectedId ? conversations.length : 0) + archivedChats.length + unboundChats.length;
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
      const serverSourceId = sourceId.startsWith("archive:")
        ? sourceId
        : page.source_id ?? sourceId;
      if (page.source_id) {
        setChatSummaries((previous) => previous.map((chat) =>
          chat.chat_id === chatId ? { ...chat, source_id: page.source_id } : chat));
        rememberChatSource(chatId, page.source_id);
      }
      setHistories((previous) => ({
        ...previous,
        [serverSourceId]: before
          ? mergeEntries(previous[serverSourceId] ?? [], entries)
          : [
              ...(previous[serverSourceId] ?? []).filter((entry) => entry.conversationId !== chatId),
              ...entries,
            ],
      }));
      if (!before && sourceId.startsWith("archive:")) {
        setActiveIds((previous) => ({ ...previous, [serverSourceId]: entries.at(-1)?.id }));
      }
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
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return;
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, []);

  useEffect(() => {
    if (!selectedId || historyListLoading) return;
    chatSummaries
      .filter((chat) => (chat.source_id ?? chatSources[chat.chat_id]) === selectedId)
      .forEach((chat) => {
        if (!loadedChats.current.has(chat.chat_id))
          void loadChatHistory(selectedId, chat.chat_id);
      });
  }, [selectedId, chatSummaries, chatSources, historyListLoading]);

  function selectSource(id: string) {
    setShowDashboardGallery(false);
    if (id !== selectedId) setAttachedDashboard(null);
    if (archivedChat && (archivedChat.source_id === null || archivedChat.source_id === undefined)) {
      const archivedKey = `archive:${archivedChat.chat_id}`;
      const existingEntries = histories[archivedKey] ?? [];
      setHistories((previous) => ({
        ...previous,
        [id]: mergeEntries(previous[id] ?? [], existingEntries),
      }));
      setActiveIds((previous) => ({
        ...previous,
        [id]: activeIds[archivedKey] ?? existingEntries.at(-1)?.id,
      }));
      activeConversations.current.set(id, archivedChat.chat_id);
    }
    setSelectedId(id);
    setArchivedChatId(null);
    setSourceSetup("csv");
    setMobilePanel("analytics");
    setMobileOverlay(null);
    setUploadFailure(null);
    setUploadError("");
    setView("overview");
  }
  function changeDraft(value: string) {
    if (selectedId)
      setDrafts((previous) => ({ ...previous, [selectedId]: value }));
  }
  function resetAnalysis() {
    setShowDashboardGallery(false);
    setAttachedDashboard(null);
    if (selectedId) {
      setActiveIds((previous) => ({ ...previous, [selectedId]: undefined }));
      activeConversations.current.delete(selectedId);
      setDrafts((previous) => ({ ...previous, [selectedId]: "" }));
    }

    setSelectedId(null);
    setArchivedChatId(null);
    setUploadedId(null);
    setUploadFailure(null);
    setUploadError("");
    setFailedFile(null);
    setSelectedUploadFile(null);
    setDragOver(false);
    setSourceSetup("csv");
    setMobilePanel("analytics");
    setView("overview");
  }
  function openArchivedChat(chat: ChatSummary) {
    setShowDashboardGallery(false);
    setAttachedDashboard(null);
    const key = `archive:${chat.chat_id}`;
    setSelectedId(null);
    setArchivedChatId(chat.chat_id);
    setActiveIds((previous) => ({
      ...previous,
      [key]: (histories[key] ?? []).filter((entry) => entry.conversationId === chat.chat_id).at(-1)?.id,
    }));
    setView("results");
    setMobilePanel("analytics");
    if (!loadedChats.current.has(chat.chat_id)) void loadChatHistory(key, chat.chat_id);
  }
  function newAnalysis() {
    if (window.matchMedia?.("(max-width: 640px)").matches) {
      setMobilePanel("home");
      setMobileOverlay("wizard");
      return;
    }
    resetAnalysis();
  }
  function newDialog() {
    if (!selectedId) return;
    setActiveIds((previous) => ({ ...previous, [selectedId]: undefined }));
    activeConversations.current.delete(selectedId);
    setDrafts((previous) => ({ ...previous, [selectedId]: "" }));
    setView("overview");
    setShowDashboardGallery(false);
    setMobilePanel("chat");
  }
  function openMobileUpload() {
    resetAnalysis();
    setMobileOverlay("upload");
  }
  function chooseTheme(value: "light" | "dark" | "system") {
    setTheme(value);
    localStorage.setItem("evia.theme", value);
  }
  function openPostgresSetup() {
    setSelectedId(null);
    setSourceSetup("postgres");
    setMobilePanel("analytics");
    void loadPostgresStatus();
  }
  async function upload(file: File, sourceId?: string) {
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
      const created = await api.upload(file, controller.signal, sourceId);
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
      setSelectedUploadFile(null);
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
    const dashboardId = retried?.dashboardId ?? attachedDashboard?.id;
    const existingConversationId = retried?.conversationId ?? activeConversations.current.get(sourceId);
    const conversationId = existingConversationId ?? crypto.randomUUID();
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
      dashboardId,
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
        const existingChatId = existingConversationId;
        chat = existingChatId
          ? Promise.resolve(existingChatId)
          : api.createChat(entry.question.slice(0, 200)).then((result) => {
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
      const answer = await api.chat(entry.question, sourceId, chatId, controller.signal, dashboardId);
      if (controller.signal.aborted)
        finish({
          state: "error",
          mascotState: "cancelled",
          error: "Ожидание остановлено. Сервер может продолжать обработку.",
        });
      else if (answer.status === "error")
        finish({ state: "error", mascotState: "error", answer, error: answer.answer });
      else {
        setChatSummaries((previous) => previous.map((chat) =>
          chat.chat_id === chatId ? { ...chat, source_id: sourceId } : chat));
        finish({ state: "success", answer, elapsedMs: answer.timing?.elapsed_ms });
      }
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
    <div className={`app mobile-panel-${mobilePanel} ${mobileOverlay === "upload" ? "mobile-upload-overlay" : ""}`} data-testid="app-shell" data-theme={theme === "system" ? systemDark ? "dark" : "light" : theme}>
      <a className="skip-link" href="#analysis">
        Перейти к данным
      </a>
      <header className="topbar">
        <a
          className="brand"
          href="#analysis"
          aria-label="EVIA, рабочее пространство"
          onClick={(event) => {
            if (window.matchMedia?.("(max-width: 640px)").matches) event.preventDefault();
            setMobilePanel("home");
          }}
        >
          EVIA
        </a>
        <button className="mobile-profile-entry" aria-label="Открыть профиль" onClick={() => setMobilePanel("profile")}><Icon name="user" size={18} /></button>
      </header>
      <div className="workspace">
        <aside className="sidebar" aria-label="Навигация рабочего пространства">
          <button className="primary new-analysis" onClick={newAnalysis}>
            <Icon name="plus" />
            Добавить источник
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
                  <span className="mobile-source-chevron"><Icon name="chevron" size={15} /></span>
                </button>
              ))}
            </div>
            <button
              className="upload-nav"
              onClick={() => {
                if (window.matchMedia?.("(max-width: 640px)").matches) openMobileUpload();
                else chooseFile();
              }}
              title="CSV · UTF-8, UTF-16 или Windows-1251"
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
                if (file) {
                  if (window.matchMedia?.("(max-width: 640px)").matches) {
                    setSelectedUploadFile(file);
                    setMobilePanel("analytics");
                  } else void upload(file);
                }
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
          <button className={`reports-nav ${showDashboardGallery ? "selected" : ""}`} type="button" aria-pressed={showDashboardGallery} onClick={() => { setShowDashboardGallery(true); setMobilePanel("analytics"); }}>
            <Icon name="grid" size={17} /> Сохранённые отчёты <Icon name="chevron" size={15} />
          </button>
          <section className="nav-section history-section">
            <div className="nav-heading">
              <h2>История диалогов</h2>
              {historyCount > 0 && (
                <span className="nav-count">{historyCount}</span>
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
            ) : (
              <>
                {failedServerChat && !history.length && (
                  <ErrorNotice
                    message={historyPages[failedServerChat.chat_id]?.error ?? "Не удалось загрузить историю."}
                    onRetry={() => historyKey && void loadChatHistory(historyKey, failedServerChat.chat_id)}
                    label="Повторить загрузку истории"
                  />
                )}
                {historyCount > 0 ? (
              <div className="history-list">
                {selectedId && [...conversations].reverse().map((entry) => (
                  <button
                    key={entry.id}
                    className={`history-item ${activeEntry?.conversationId === entry.conversationId ? "active" : ""}`}
                    aria-label={entry.question}
                    title={entry.question}
                    aria-pressed={activeEntry?.conversationId === entry.conversationId}
                    onClick={() => {
                      if (historyKey) {
                        activeConversations.current.set(historyKey, entry.conversationId!);
                        setActiveIds((previous) => ({
                          ...previous,
                          [historyKey]: history.filter((item) => item.conversationId === entry.conversationId).at(-1)?.id,
                        }));
                      }
                      setView("results");
                      setShowDashboardGallery(false);
                      setMobilePanel("analytics");
                    }}
                  >
                    <Icon name="chat" size={16} />
                    <span>{entry.question}</span>
                    {history.some((item) => item.conversationId === entry.conversationId && item.state === "pending") && (
                      <span className="pending-dot" />
                    )}
                  </button>
                ))}
                {archivedChats.map((chat) => (
                  <button
                    key={chat.chat_id}
                    className={`history-item ${archivedChatId === chat.chat_id ? "active" : ""}`}
                    aria-label={`Архив: ${chat.title}`}
                    title={`Источник недоступен · ${chat.title}`}
                    onClick={() => openArchivedChat(chat)}
                  >
                    <Icon name="chat" size={16} />
                    <span>{chat.title}</span>
                  </button>
                ))}
                {unboundChats.map((chat) => (
                  <button
                    key={chat.chat_id}
                    className={`history-item ${archivedChatId === chat.chat_id ? "active" : ""}`}
                    aria-label={`Без источника: ${chat.title}`}
                    title={`Без источника · ${chat.title}`}
                    onClick={() => openArchivedChat(chat)}
                  >
                    <Icon name="chat" size={16} />
                    <span>{chat.title}</span>
                  </button>
                ))}
              </div>
                ) : !failedServerChat && (
                  <p className="sidebar-note">Нет диалогов</p>
                )}
              </>
            )}
          </section>
        </aside>
        <main
          className={`analysis ${source ? "" : "analysis-empty"}`}
          id="analysis"
          tabIndex={-1}
        >
          <div className="mobile-page-header">
            <button aria-label={mobileOverlay === "upload" ? "Закрыть загрузку CSV" : "Назад к источникам"} onClick={() => { setMobileOverlay(null); setMobilePanel("home"); }}>
              <Icon name="back" size={22} />
            </button>
            <strong>{showDashboardGallery ? "Отчёты" : source ? "Анализ данных" : sourceSetup === "postgres" ? "PostgreSQL" : "Загрузка CSV"}</strong>
            <span aria-hidden="true" />
          </div>
          {showDashboardGallery ? (
            <DashboardGallery onClose={() => setShowDashboardGallery(false)} onAttach={source ? (id, title) => {
              setAttachedDashboard({ id, title });
              setShowDashboardGallery(false);
              setMobilePanel("chat");
            } : undefined} />
          ) : source ? (
            <SourceInspector
              source={source}
              entry={activeEntry}
              view={view}
              setView={setView}
              onReimport={(file, id) => void upload(file, id)}
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
                role={mobileOverlay === "upload" ? "dialog" : undefined}
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
                  if (file) {
                    if (window.matchMedia?.("(max-width: 640px)").matches) setSelectedUploadFile(file);
                    else void upload(file);
                  }
                }}
                aria-label={mobileOverlay === "upload" ? "Загрузка CSV" : "Добавление источника"}
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
                <p>Перетащите файл сюда или выберите его с устройства</p>
                {selectedUploadFile && <div className="upload-selected-file">
                  <Icon name="file" size={18} />
                  <span>{selectedUploadFile.name}<small>{(selectedUploadFile.size / 1024).toFixed(1)} КБ</small></span>
                  <Icon name="check" size={16} />
                </div>}
                {uploadError && window.matchMedia?.("(max-width: 640px)").matches && <div className="mobile-upload-error"><ErrorNotice
                  message={uploadError}
                  onRetry={failedFile ? () => void upload(failedFile) : chooseFile}
                  label={failedFile ? "Повторить загрузку CSV" : "Выбрать файл"}
                /></div>}
                <button
                  className="primary"
                  onClick={() => selectedUploadFile ? void upload(selectedUploadFile) : chooseFile()}
                  disabled={uploading}
                >
                  <Icon name="upload" />
                  {uploading ? "Загружаем…" : selectedUploadFile ? "Загрузить файл" : "Выбрать CSV"}
                </button>
                <small>UTF-8, UTF-16 или Windows-1251 · до 512 МиБ</small>
              </section>
              <details className="upload-advanced"><summary>Дополнительно</summary><p>Поддерживаются UTF-8, UTF-16 и Windows-1251; разделители — запятая, точка с запятой, табуляция и вертикальная черта. Первая строка содержит уникальные названия столбцов. Для замены данных откройте «Схема» у нужного источника.</p></details>
            </>
          )}
        </main>
        <aside className="chat-panel" aria-label="Чат с EVIA">
          <header className="chat-header">
            <h2>AI-помощник</h2><strong className="mobile-chat-brand">EVIA</strong>
            {source && <button className="new-dialog" type="button" onClick={newDialog}><Icon name="plus" size={15} /> Новый диалог</button>}
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
                      onRetry={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
                      label="Повторить загрузку истории"
                    />
                  ) : (
                    <button
                      className="text-button"
                      onClick={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
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
                      {message.answer?.clarification?.options && (
                        <div className="clarification-options" aria-label="Варианты уточнения">
                          {message.answer.clarification.options.map((option, index) => (
                            <button
                              className="text-button"
                              key={option}
                              onClick={() => void send(String(index + 1))}
                            >
                              {index + 1}. {option}
                            </button>
                          ))}
                        </div>
                      )}
                      {message.historyDetail && (
                        <p className="history-details-notice" role="status">
                          {message.historyDetail === "legacy"
                            ? "Это старый текстовый ответ: SQL, таблица и время тогда не сохранялись."
                            : message.historyDetail === "unsupported"
                              ? "Сохранённые детали созданы более новой версией EVIA и пока показаны только текстом."
                              : "Сохранённые детали этого ответа повреждены, поэтому показан только текст."}
                        </p>
                      )}
                      {!message.historyDetail && Boolean(message.answer?.tool_results.length || message.answer?.analysis?.sql) && <button
                        className="result-link"
                        onClick={() => {
                          if (historyKey) setActiveIds((previous) => ({ ...previous, [historyKey]: message.id }));
                          setView("results");
                          setShowDashboardGallery(false);
                          setMobilePanel("analytics");
                        }}
                      >
                        <Icon name="grid" />
                        Открыть результат
                        <Icon name="chevron" size={15} />
                      </button>
                      }
                    </>
                  )}
                  <ResponseTiming key={`${message.id}-${message.startedAt}`} entry={message} />
                </section>
              </article>)}
              </>
            ) : (
              <div className="chat-welcome">
                <Evia large state={mascotState} />
                <h3>{source ? "Спросите о своих данных" : "Добавьте источник данных"}</h3>
                <p className="mobile-chat-intro">{source ? "EVIA поможет найти ответ, построить график или разобраться в таблице." : "Загрузите CSV или подключите PostgreSQL, чтобы начать анализ."}</p>
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
                      "Построй график распределения",
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
            {attachedDashboard && source && <div className="attached-report" aria-label="Прикреплённый отчёт"><span>Отчёт: <strong>{attachedDashboard.title}</strong></span><button type="button" aria-label="Открепить отчёт" onClick={() => setAttachedDashboard(null)}><Icon name="close" size={14} /></button></div>}
            {activeEntry && <div className="helper" role="status"><Evia state={mascotState} />{activeEntry.state === "pending" && <strong>{eviaStatus(mascotState)}</strong>}</div>}
            {archivedChat && !archivedChat.source_id && (
              <p className="history-details-notice">
                Для продолжения этого старого диалога выберите источник в левой панели.
              </p>
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
            {source && <div className="mobile-chat-source" aria-label="Прикреплённый источник"><Icon name="file" size={14} /><span>{source.name}{source.source_type === "csv" && !source.name.toLowerCase().endsWith(".csv") ? ".csv" : ""}</span><button type="button" aria-label="Убрать источник из чата" onClick={() => setSelectedId(null)}><Icon name="close" size={14} /></button></div>}
            <div className="composer-hint">
              <span>Ctrl / ⌘ + Enter — отправить</span>
              {draft.length > 3500 && <span>{draft.length}/4000</span>}
            </div>
            <details className="chat-help">
              <summary>О чате</summary>
              <p>
                Вопросы продолжают выбранный диалог: модель получает предыдущие
                сообщения. «Добавить источник» открывает экран загрузки данных. У каждого
                источника своя история. Сообщения сохраняются на сервере;
                список диалогов этой вкладки пока доступен до обновления страницы.
              </p>
            </details>
          </div>
        </aside>
      </div>
      <section className="mobile-profile" aria-label="Профиль и настройки">
        <header className="mobile-page-header">
          <button aria-label="Назад к источникам" onClick={() => setMobilePanel("home")}>
            <Icon name="back" size={22} />
          </button>
          <strong>Профиль</strong>
          <span aria-hidden="true" />
        </header>
        <div className="mobile-profile-card">
          <span className="mobile-profile-avatar"><Icon name="user" size={24} /></span>
          <div><strong>Гостевой доступ</strong><small>Ваши источники доступны в этом рабочем пространстве</small></div>
        </div>
        <div className="mobile-profile-list">
          <button type="button" onClick={() => setMobileOverlay("settings")} aria-label="Открыть настройки"><strong>Настройки</strong><Icon name="chevron" size={16} /></button>
          <div><strong>Язык</strong><span>Русский</span></div>
          <div><strong>О приложении</strong><span>EVIA</span></div>
        </div>
      </section>
      {mobileOverlay === "wizard" && <section className="mobile-fullscreen mobile-wizard" role="dialog" aria-label="Новый анализ" aria-modal="true">
        <header><h2>Новый анализ</h2><button aria-label="Закрыть новый анализ" onClick={() => setMobileOverlay(null)}><Icon name="close" size={19} /></button></header>
        <ol className="wizard-steps">
          <li className="active"><b>1</b><span>Загрузка данных</span></li>
          <li><b>2</b><span>Настройка</span></li>
          <li><b>3</b><span>Анализ</span></li>
          <li><b>4</b><span>Результат</span></li>
        </ol>
        {sources.length > 0 && <div className="wizard-existing"><h3>Или выберите источник</h3>{sources.slice(0, 3).map((item) => <button key={item.source_id} aria-label={`Использовать ${item.name}`} onClick={() => { resetAnalysis(); selectSource(item.source_id); }}><Icon name="file" size={18} /><span><strong>{item.name}</strong><small>{item.source_type.toUpperCase()}</small></span><Icon name="chevron" size={15} /></button>)}</div>}
        <div className="wizard-bottom"><button className="primary" aria-label="Загрузить CSV в новом анализе" onClick={openMobileUpload}>Загрузить CSV <Icon name="arrow" size={17} /></button><button className="wizard-postgres" onClick={() => { setMobileOverlay(null); openPostgresSetup(); }}>Подключить PostgreSQL</button></div>
      </section>}
      {mobileOverlay === "settings" && <section className="mobile-fullscreen mobile-settings" role="dialog" aria-label="Настройки" aria-modal="true">
        <header><h2>Настройки</h2><button aria-label="Закрыть настройки" onClick={() => setMobileOverlay(null)}><Icon name="close" size={19} /></button></header>
        <h3>Тема</h3>
        <div className="settings-options">
          {([ ["light", "Светлая"], ["dark", "Тёмная"], ["system", "Системная"] ] as const).map(([value, label]) => <button key={value} aria-label={`${label} тема`} aria-pressed={theme === value} onClick={() => chooseTheme(value)}><span>{label}</span>{theme === value && <Icon name="check" size={16} />}</button>)}
        </div>
        <div className="settings-info"><span>Язык</span><strong>Русский</strong></div>
      </section>}
      <nav className="mobile-nav" aria-label="Мобильная навигация">
        <button
          aria-label="Главная"
          aria-pressed={mobilePanel === "home"}
          onClick={() => setMobilePanel("home")}
        >
          <Icon name="home" size={18} />
          <span>Главная</span>
        </button>
        <button
          aria-label="Аналитика"
          aria-pressed={mobilePanel === "analytics"}
          onClick={() => setMobilePanel("analytics")}
        >
          <Icon name="file" size={18} />
          <span>Аналитика</span>
        </button>
        <button
          aria-label="Чат"
          aria-pressed={mobilePanel === "chat"}
          onClick={() => setMobilePanel("chat")}
        >
          <Icon name="chat" size={18} />
          <span>Чат</span>
        </button>
        <button
          aria-label="Профиль"
          aria-pressed={mobilePanel === "profile"}
          onClick={() => setMobilePanel("profile")}
        >
          <Icon name="user" size={18} />
          <span>Профиль</span>
        </button>
      </nav>
    </div>
  );
}
