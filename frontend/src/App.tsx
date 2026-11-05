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
import { AccountMenu } from "./AccountMenu";
import { LanguageSwitch, useLanguage } from "./language";
import type { Account } from "./authApi";
import "./styles.css";
import {
  resolveEviaState,
  errorEviaState,
  eviaStatus,
} from "./features/mascot/resolveEviaState";
import type { EviaState } from "./features/mascot/states";
import { WelcomeGreeting, welcomeGreetings } from "./features/mascot/WelcomeGreeting";

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

function entriesFromMessages(chatId: string, messages: ChatMessage[], language: "ru" | "en"): Entry[] {
  const entries: Entry[] = [];
  let user: ChatMessage | undefined;
  for (const [index, message] of messages.entries()) {
    if (message.role === "user") {
      // The agent stores this internal continuation prompt in its trace. It is
      // not a new question from the person who owns the chat.
      if (user && message.content === "Продолжи ответ точно с места обрыва, без повторения уже написанного.") continue;
      user = message;
      continue;
    }
    if (message.role === "assistant" && user) {
      const restored = storedAnalysis(message);
      // Tool calls and partial model output precede the saved final answer.
      // Neither is a standalone response to the user's question.
      if (restored.kind !== "restored" && (
        message.tool_calls?.length || !message.content.trim() ||
        (messages[index + 1]?.role === "user" &&
          messages[index + 1]?.content === "Продолжи ответ точно с места обрыва, без повторения уже написанного.")
      )) continue;
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
      error: language === "en" ? "The answer to this question was not saved. Please retry." : "Ответ для этого вопроса не сохранился. Повторите запрос.",
    });
  }
  return entries;
}

function mergeEntries(existing: Entry[], loaded: Entry[]): Entry[] {
  const known = new Set(existing.map((entry) => entry.id));
  return [...loaded.filter((entry) => !known.has(entry.id)), ...existing];
}

export default function App({ account, onAccountChange, onLogout }: {
  account?: Account;
  onAccountChange?: (account: Account) => void;
  onLogout?: () => Promise<void>;
} = {}) {
  const { t, language } = useLanguage();
  const [sources, setSources] = useState<Source[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState("");
  const [postgresStatus, setPostgresStatus] = useState<PostgresStatus | null>(null);
  const [postgresLoading, setPostgresLoading] = useState(false);
  const [postgresError, setPostgresError] = useState("");
  const [sourceSetup, setSourceSetup] = useState<"csv" | "postgres">("csv");
  const [welcomeGreeting] = useState(() => welcomeGreetings[Math.floor(Math.random() * welcomeGreetings.length)]);
  const [mobilePanel, setMobilePanel] = useState<"home" | "analytics" | "chat">("home");
  const [mobileOverlay, setMobileOverlay] = useState<"upload" | "settings" | null>(null);
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
  const [showDashboardGallery, setShowDashboardGallery] = useState(() =>
    new URLSearchParams(window.location.search).has("dashboard"));
  const [attachedDashboard, setAttachedDashboard] = useState<{ id: string; title: string } | null>(null);
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const [uploadFailure, setUploadFailure] = useState<EviaState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const [selectedUploadFile, setSelectedUploadFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const settingsDialog = useRef<HTMLElement>(null);
  const settingsReturnFocus = useRef<HTMLElement | null>(null);
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
      const entries = entriesFromMessages(chatId, page.messages, language);
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
    if (showDashboardGallery) return;
    const url = new URL(window.location.href);
    if (url.searchParams.has("dashboard")) {
      url.searchParams.delete("dashboard");
      window.history.replaceState({}, "", url);
    }
  }, [showDashboardGallery]);

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
    if (mobileOverlay !== "settings") return;
    const dialog = settingsDialog.current;
    const buttons = Array.from(dialog?.querySelectorAll("button") ?? []);
    buttons[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOverlay(null);
      } else if (event.key === "Tab" && buttons.length) {
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      settingsReturnFocus.current?.focus();
    };
  }, [mobileOverlay]);

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
  function openDashboardOrigin(chatId: string): boolean {
    const chat = chatSummaries.find((item) => item.chat_id === chatId);
    if (!chat) return false;
    const sourceId = chat.source_id ?? chatSources[chat.chat_id];
    if (!sourceId || !sources.some((item) => item.source_id === sourceId)) {
      openArchivedChat(chat);
      return true;
    }
    selectSource(sourceId);
    activeConversations.current.set(sourceId, chatId);
    setActiveIds((previous) => ({
      ...previous,
      [sourceId]: (histories[sourceId] ?? []).filter((entry) => entry.conversationId === chatId).at(-1)?.id,
    }));
    setView("results");
    if (!loadedChats.current.has(chatId)) void loadChatHistory(sourceId, chatId);
    return true;
  }
  function newAnalysis() {
    if (window.matchMedia?.("(max-width: 640px)").matches) {
      openMobileUpload();
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
    setSelectedUploadFile(null);
    setUploadError("");
    setFailedFile(null);
    setMobilePanel("analytics");
    setMobileOverlay("upload");
  }
  function openSettings() {
    settingsReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setMobileOverlay("settings");
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
      setUploadError(t("Поддерживаются только файлы .csv.", "Only .csv files are supported."));
      return;
    }
    if (file.size === 0) {
      setUploadFailure("invalid_csv");
      setUploadError(t("Файл пуст. Выберите CSV с заголовком и данными.", "The file is empty. Choose a CSV with a header and data."));
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const created = await api.upload(file, controller.signal, sourceId, setUploadProgress);
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
      if (!controller.signal.aborted) {
        setUploading(false);
        setUploadProgress(null);
      }
    }
  }
  async function deleteSource(id: string) {
    await api.deleteSource(id);
    sourceController.current?.abort();
    setSources((previous) => previous.filter((item) => item.source_id !== id));
    setSelectedId((current) => current === id ? null : current);
    setUploadedId((current) => current === id ? null : current);
    setAttachedDashboard(null);
    setSourceSetup("csv");
    setMobilePanel("analytics");
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
          error: t("Ожидание остановлено. Сервер может продолжать обработку.", "Waiting stopped. The server may continue processing."),
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
          ? t("Ожидание остановлено. Сервер может продолжать обработку.", "Waiting stopped. The server may continue processing.")
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
        {t("Перейти к данным", "Go to data")}
      </a>
      <header className="topbar">
        <a
          className="brand"
          href="#analysis"
          aria-label={t("EVIA, рабочее пространство", "EVIA workspace")}
          onClick={(event) => {
            if (window.matchMedia?.("(max-width: 640px)").matches) event.preventDefault();
            setMobilePanel("home");
          }}
        >
          EVIA
        </a>
        {account && onAccountChange && onLogout && <AccountMenu account={account} onChange={onAccountChange} onLogout={onLogout} theme={theme === "system" ? systemDark ? "dark" : "light" : theme} />}
        <button className="mobile-settings-entry" aria-label={t("Открыть настройки", "Open settings")} onClick={openSettings}><Icon name="settings" size={18} /></button>
      </header>
      <div className="workspace">
        <aside className="sidebar" aria-label={t("Навигация рабочего пространства", "Workspace navigation")}>
          <button className="primary new-analysis" onClick={newAnalysis}>
            <Icon name="plus" />
            {t("Добавить источник", "Add source")}
          </button>
          {!sourcesLoading && <div className="mobile-home-greeting"><WelcomeGreeting greeting={welcomeGreeting} activeState={mascotState} /></div>}
          <section className="nav-section">
            <div className="nav-heading">
              <h2>{t("Источники", "Sources")}</h2>
              <button
                className="icon-button"
                aria-label={t("Обновить источники", "Refresh sources")}
                onClick={() => void loadSources()}
                disabled={sourcesLoading}
              >
                <Icon name="refresh" size={15} />
              </button>
            </div>
            {sourcesLoading && (
              <p className="sidebar-note" role="status">
                {t("Загружаем источники…", "Loading sources…")}
              </p>
            )}
            {sourcesError && (
              <ErrorNotice
                message={sourcesError}
                onRetry={() => void loadSources()}
              />
            )}
            {!sourcesLoading && !sourcesError && !sources.length && (
              <p className="sidebar-note">{t("Нет источников", "No sources")}</p>
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
              title={t("CSV · UTF-8, UTF-16 или Windows-1251", "CSV · UTF-8, UTF-16 or Windows-1251")}
              disabled={uploading}
            >
              <Icon name="plus" size={16} />
              {uploading ? uploadProgress === 100 ? t("Обрабатываем CSV…", "Processing CSV…") : t(`Загружаем CSV · ${uploadProgress ?? 0}%`, `Uploading CSV · ${uploadProgress ?? 0}%`) : t("Добавить CSV", "Add CSV")}
            </button>
            <button
              className={`postgres-nav ${!source && sourceSetup === "postgres" ? "selected" : ""}`}
              onClick={openPostgresSetup}
              aria-pressed={!source && sourceSetup === "postgres"}
              title={postgresStatus?.connected ? t("PostgreSQL доступен", "PostgreSQL available") : undefined}
            >
              {t("Подключить PostgreSQL", "Connect PostgreSQL")}
            </button>
            <input
              className="visually-hidden"
              type="file"
              accept=".csv,text/csv"
              aria-label={t("Загрузить CSV", "Upload CSV")}
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
                label={failedFile ? t("Повторить загрузку CSV", "Retry CSV upload") : t("Выбрать файл", "Choose file")}
              />
            )}
          </section>
          <button className={`reports-nav ${showDashboardGallery ? "selected" : ""}`} type="button" aria-pressed={showDashboardGallery} onClick={() => { setShowDashboardGallery(true); setMobilePanel("analytics"); }}>
            {t("Сохранённые отчёты", "Saved reports")} <Icon name="chevron" size={15} />
          </button>
          <section className="nav-section history-section">
            <div className="nav-heading">
              <h2>{t("История диалогов", "Chat history")}</h2>
              {historyCount > 0 && (
                <span className="nav-count">{historyCount}</span>
              )}
            </div>
            {historyListLoading ? (
              <p className="sidebar-note" role="status">{t("Загружаем диалоги…", "Loading chats…")}</p>
            ) : historyListError ? (
              <ErrorNotice
                message={historyListError}
                onRetry={() => void loadChatList()}
                label={t("Повторить загрузку диалогов", "Retry loading chats")}
              />
            ) : (
              <>
                {failedServerChat && !history.length && (
                  <ErrorNotice
                    message={historyPages[failedServerChat.chat_id]?.error ?? t("Не удалось загрузить историю.", "Could not load history.")}
                    onRetry={() => historyKey && void loadChatHistory(historyKey, failedServerChat.chat_id)}
                    label={t("Повторить загрузку истории", "Retry loading history")}
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
                    aria-label={t(`Архив: ${chat.title}`, `Archive: ${chat.title}`)}
                    title={t(`Источник недоступен · ${chat.title}`, `Source unavailable · ${chat.title}`)}
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
                    aria-label={t(`Без источника: ${chat.title}`, `No source: ${chat.title}`)}
                    title={t(`Без источника · ${chat.title}`, `No source · ${chat.title}`)}
                    onClick={() => openArchivedChat(chat)}
                  >
                    <Icon name="chat" size={16} />
                    <span>{chat.title}</span>
                  </button>
                ))}
              </div>
                ) : !failedServerChat && (
                  <p className="sidebar-note">{t("Нет диалогов", "No chats")}</p>
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
            <button aria-label={mobileOverlay === "upload" ? t("Закрыть загрузку CSV", "Close CSV upload") : t("Назад к источникам", "Back to sources")} onClick={() => { setMobileOverlay(null); setMobilePanel("home"); }}>
              <Icon name="back" size={22} />
            </button>
            <strong>{mobileOverlay === "upload" ? t("Загрузка CSV", "CSV upload") : showDashboardGallery ? t("Отчёты", "Reports") : source ? t("Данные источника", "Source data") : sourceSetup === "postgres" ? "PostgreSQL" : t("Загрузка CSV", "CSV upload")}</strong>
            <span aria-hidden="true" />
          </div>
          {showDashboardGallery && mobileOverlay !== "upload" ? (
            <DashboardGallery onClose={() => setShowDashboardGallery(false)} onOpenOrigin={openDashboardOrigin} onAttach={source ? (id, title) => {
              setAttachedDashboard({ id, title });
              setShowDashboardGallery(false);
              setMobilePanel("chat");
            } : undefined} />
          ) : source && mobileOverlay !== "upload" ? (
            <SourceInspector
              source={source}
              entry={activeEntry}
              reportEntries={history}
              view={view}
              setView={setView}
              onOpenChat={() => setMobilePanel("chat")}
              onReimport={(file, id) => void upload(file, id)}
              onDelete={deleteSource}
              deleteDisabled={uploading || Boolean(pending)}
            />
          ) : sourceSetup === "postgres" && mobileOverlay !== "upload" ? (
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
                aria-label={mobileOverlay === "upload" ? t("Загрузка CSV", "CSV upload") : t("Добавление источника", "Add source")}
              >
                {!sourcesLoading && <WelcomeGreeting greeting={welcomeGreeting} activeState={mascotState} />}
              <h1>{uploading ? uploadProgress === 100 ? t("Обрабатываем CSV…", "Processing CSV…") : t(`Загрузка CSV · ${uploadProgress ?? 0}%`, `Uploading CSV · ${uploadProgress ?? 0}%`) : t("Добавьте CSV", "Add CSV")}</h1>
                <p>{t("Перетащите файл сюда или выберите его с устройства", "Drag a file here or choose one from your device")}</p>
                {selectedUploadFile && <div className="upload-selected-file">
                  <Icon name="file" size={18} />
                  <span>{selectedUploadFile.name}<small>{(selectedUploadFile.size / 1024).toFixed(1)} {t("КБ", "KB")}</small></span>
                  <Icon name="check" size={16} />
                </div>}
                {uploadError && window.matchMedia?.("(max-width: 640px)").matches && <div className="mobile-upload-error"><ErrorNotice
                  message={uploadError}
                  onRetry={failedFile ? () => void upload(failedFile) : chooseFile}
                  label={failedFile ? t("Повторить загрузку CSV", "Retry CSV upload") : t("Выбрать файл", "Choose file")}
                /></div>}
                <button
                  className="primary"
                  onClick={() => selectedUploadFile ? void upload(selectedUploadFile) : chooseFile()}
                  disabled={uploading}
                >
                  <Icon name="upload" />
                  {uploading ? uploadProgress === 100 ? t("Обрабатываем…", "Processing…") : t(`Загружаем · ${uploadProgress ?? 0}%`, `Uploading · ${uploadProgress ?? 0}%`) : selectedUploadFile ? t("Загрузить файл", "Upload file") : t("Выбрать CSV", "Choose CSV")}
                </button>
                <small>{t("UTF-8, UTF-16 или Windows-1251 · до 512 МиБ", "UTF-8, UTF-16 or Windows-1251 · up to 512 MiB")}</small>
              </section>
              <details className="upload-advanced"><summary>{t("Дополнительно", "More details")}</summary><p>{t("Поддерживаются UTF-8, UTF-16 и Windows-1251; разделители — запятая, точка с запятой, табуляция и вертикальная черта. Первая строка содержит уникальные названия столбцов. Для замены данных откройте «Схема» у нужного источника.", "Supported encodings: UTF-8, UTF-16 and Windows-1251; delimiters: comma, semicolon, tab and vertical bar. The first row must contain unique column names. To replace data, open the source's Schema tab.")}</p></details>
            </>
          )}
        </main>
        <aside className="chat-panel" aria-label={t("Чат с EVIA", "Chat with EVIA")}>
          <header className="chat-header">
            <h2>{t("AI-помощник", "AI assistant")}</h2><strong className="mobile-chat-brand">EVIA</strong>
            {source && <button className="new-dialog" type="button" onClick={newDialog}><Icon name="plus" size={15} /> {t("Новый диалог", "New chat")}</button>}
          </header>
          <div className="chat-content">
            {activeEntry ? (
              <>
              {activePage?.hasMore && (
                <div className="history-pagination">
                  {activePage.loading ? (
                    <p role="status">{t("Загружаем предыдущие сообщения…", "Loading previous messages…")}</p>
                  ) : activePage.error ? (
                    <ErrorNotice
                      message={activePage.error}
                      onRetry={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
                      label={t("Повторить загрузку истории", "Retry loading history")}
                    />
                  ) : (
                    <button
                      className="text-button"
                      onClick={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
                    >
                      {t("Показать предыдущие сообщения", "Show previous messages")}
                    </button>
                  )}
                </div>
              )}
              {conversationEntries.map((message) => <article key={message.id} className="chat-turn">
                <div className="user-message">{message.question}</div>
                <section className="assistant-message" aria-label={t("Ответ EVIA", "EVIA response")}>
                  <div className="reply-label">EVIA</div>
                  {message.state === "pending" ? (
                    <div className="thinking" role="status">
                      <span />
                      <span />
                      <span />
                      <p>{t("Изучаю ваш вопрос…", "Looking into your question…")}</p>
                    </div>
                  ) : message.state === "error" ? (
                    <ErrorNotice
                      message={
                        message.error ?? t("Не удалось получить ответ.", "Could not get a response.")
                      }
                      onRetry={() =>
                        void send(message.question, message.id)
                      }
                      label={t("Повторить вопрос", "Retry question")}
                    />
                  ) : (
                    <>
                      <SafeMarkdown>
                        {message.answer?.answer ||
                          t("Модель вернула пустой ответ.", "The model returned an empty response.")}
                      </SafeMarkdown>
                      {message.answer?.clarification?.options && (
                        <div className="clarification-options" aria-label={t("Варианты уточнения", "Clarification options")}>
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
                            ? t("Это старый текстовый ответ: SQL, таблица и время тогда не сохранялись.", "This is an old text-only response; SQL, tables and timing were not saved.")
                            : message.historyDetail === "unsupported"
                              ? t("Сохранённые детали созданы более новой версией EVIA и пока показаны только текстом.", "The saved details were created by a newer EVIA version and are shown as text only.")
                              : t("Сохранённые детали этого ответа повреждены, поэтому показан только текст.", "The saved details are damaged, so only text is shown.")}
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
                        {t("Открыть результат", "Open result")}
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
                {source && !sourcesLoading && <WelcomeGreeting greeting={welcomeGreeting} activeState={mascotState} />}
                <h3>{source ? t("Спросите о своих данных", "Ask about your data") : t("Добавьте источник данных", "Add a data source")}</h3>
                <p className="mobile-chat-intro">{source ? t("EVIA поможет найти ответ, построить график или разобраться в таблице.", "EVIA can answer questions, create charts and help you explore your data.") : t("Загрузите CSV или подключите PostgreSQL, чтобы начать анализ.", "Upload a CSV or connect PostgreSQL to start analyzing.")}</p>
                <p
                  className={`evia-live-status ${["welcome", "waiting", "listening", "explaining"].includes(mascotState) ? "visually-hidden" : ""}`}
                  role="status"
                >
                  {eviaStatus(mascotState, language)}
                </p>
                {source && (
                  <div className="suggestions">
                    {[
                      t("Какие есть столбцы?", "What columns are available?"),
                      t("Покажи первые строки", "Show the first rows"),
                      t("Есть ли пропуски?", "Are there missing values?"),
                      t("Построй график распределения", "Plot the distribution"),
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
            {attachedDashboard && source && <div className="attached-report" aria-label={t("Прикреплённый отчёт", "Attached report")}><span>{t("Отчёт", "Report")}: <strong>{attachedDashboard.title}</strong></span><button type="button" aria-label={t("Открепить отчёт", "Detach report")} onClick={() => setAttachedDashboard(null)}><Icon name="close" size={14} /></button></div>}
            {activeEntry && <div className="helper" role="status"><Evia state={mascotState} />{activeEntry.state === "pending" && <strong>{eviaStatus(mascotState, language)}</strong>}</div>}
            {archivedChat && !archivedChat.source_id && (
              <p className="history-details-notice">
                {t("Для продолжения этого старого диалога выберите источник в левой панели.", "To continue this old chat, select a source in the left panel.")}
              </p>
            )}
            <form className="composer" onSubmit={submit}>
              <label className="visually-hidden" htmlFor="question">
                {t("Ваш вопрос", "Your question")}
              </label>
              <textarea
                id="question"
                ref={composer}
                placeholder={
                  source
                    ? t("Что хотите узнать о данных?", "What would you like to know about your data?")
                    : t("Сначала добавьте источник…", "First add a data source…")
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
                    t("Источник не выбран", "No source selected")
                  )}
                </span>
                {pending ? (
                  <button
                    type="button"
                    className="stop-button"
                    aria-label={t("Прекратить ожидание", "Stop waiting")}
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
                    aria-label={t("Отправить вопрос", "Send question")}
                    disabled={
                      !source || !draft.trim() || draft.trim().length > 4000
                    }
                  >
                    <Icon name="arrow" />
                  </button>
                )}
              </div>
            </form>
            {source && <div className="mobile-chat-source" aria-label={t("Прикреплённый источник", "Attached source")}><Icon name="file" size={14} /><span>{source.name}{source.source_type === "csv" && !source.name.toLowerCase().endsWith(".csv") ? ".csv" : ""}</span><button type="button" aria-label={t("Убрать источник из чата", "Remove source from chat")} onClick={() => setSelectedId(null)}><Icon name="close" size={14} /></button></div>}
            <div className="composer-hint">
              <span>{t("Ctrl / ⌘ + Enter — отправить", "Ctrl / ⌘ + Enter to send")}</span>
              {draft.length > 3500 && <span>{draft.length}/4000</span>}
            </div>
          </div>
        </aside>
      </div>
      {mobileOverlay === "settings" && <div className="settings-backdrop" data-testid="settings-backdrop" aria-hidden="true" onClick={() => setMobileOverlay(null)} />}
      {mobileOverlay === "settings" && <section className="mobile-fullscreen mobile-settings" role="dialog" aria-label={t("Настройки", "Settings")} aria-modal="true" ref={settingsDialog}>
        <header><h2>{t("Настройки", "Settings")}</h2><button aria-label={t("Закрыть настройки", "Close settings")} onClick={() => setMobileOverlay(null)}><Icon name="close" size={19} /></button></header>
        <h3>{t("Тема", "Theme")}</h3>
        <div className="settings-options">
          {([ ["light", t("Светлая", "Light")], ["dark", t("Тёмная", "Dark")], ["system", t("Системная", "System")] ] as const).map(([value, label]) => <button key={value} aria-label={t(`${label} тема`, `${label} theme`)} aria-pressed={theme === value} onClick={() => chooseTheme(value)}><span>{label}</span>{theme === value && <Icon name="check" size={16} />}</button>)}
        </div>
        <h3>{t("Язык", "Language")}</h3><LanguageSwitch />
      </section>}
      <nav className="mobile-nav" aria-label={t("Мобильная навигация", "Mobile navigation")}>
        <button
          aria-label={t("Источники", "Sources")}
          aria-pressed={mobilePanel === "home"}
          onClick={() => setMobilePanel("home")}
        >
          <Icon name="home" size={18} />
          <span>{t("Источники", "Sources")}</span>
        </button>
        <button
          aria-label={t("Рабочее пространство", "Workspace")}
          aria-pressed={mobilePanel === "analytics"}
          onClick={() => setMobilePanel("analytics")}
        >
          <Icon name="file" size={18} />
          <span>{t("Данные", "Data")}</span>
        </button>
        <button
          aria-label={t("Чат", "Chat")}
          aria-pressed={mobilePanel === "chat"}
          onClick={() => setMobilePanel("chat")}
        >
          <Icon name="chat" size={18} />
          <span>{t("Чат", "Chat")}</span>
        </button>
        <button
          aria-label={t("Настройки", "Settings")}
          aria-pressed={mobileOverlay === "settings"}
          onClick={openSettings}
        >
          <Icon name="settings" size={18} />
          <span>{t("Настройки", "Settings")}</span>
        </button>
      </nav>
    </div>
  );
}
