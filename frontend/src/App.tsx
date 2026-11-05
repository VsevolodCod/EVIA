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
import type { Account } from "./authApi";
import "./styles.css";
import {
  resolveEviaState,
  errorEviaState,
  eviaStatus,
} from "./features/mascot/resolveEviaState";
import type { EviaState } from "./features/mascot/states";
import { WelcomeGreeting, welcomeGreetings } from "./features/mascot/WelcomeGreeting";
import { HomePage } from "./features/home/HomePage";
import { LanguageProvider, useLanguage } from "./i18n";

const CHAT_SOURCE_STORAGE_KEY = "evia.chat-sources.v1";

type ChatPage = {
  hasMore: boolean;
  nextBefore: number | null;
  loading: boolean;
  error: string;
};

type WorkspaceScreen = "home" | "analysis" | "chat" | "reports" | "postgres";
type AnalysisView = View;

function readWorkspaceRoute(): { screen: WorkspaceScreen; sourceId: string | null; view: AnalysisView; chatId: string | null } {
  const url = new URL(window.location.href);
  const rawScreen = url.searchParams.get("page");
  const allowed: WorkspaceScreen[] = ["home", "analysis", "chat", "reports", "postgres"];
  const screen = allowed.includes(rawScreen as WorkspaceScreen)
    ? rawScreen as WorkspaceScreen
    : url.searchParams.has("dashboard") ? "reports"
      : url.searchParams.has("source") ? "analysis" : "home";
  const rawView = url.searchParams.get("view");
  const views: AnalysisView[] = ["overview", "profile", "quality", "preview", "schema", "results"];
  return {
    screen,
    sourceId: url.searchParams.get("source"),
    chatId: url.searchParams.get("chat"),
    view: views.includes(rawView as AnalysisView) ? rawView as AnalysisView : "overview",
  };
}

function workspaceUrl(screen: WorkspaceScreen, sourceId: string | null, view: AnalysisView, chatId?: string | null): string {
  const url = new URL(window.location.href);
  url.search = "";
  if (screen !== "home") url.searchParams.set("page", screen);
  if (sourceId && screen !== "home") url.searchParams.set("source", sourceId);
  if (screen === "analysis") url.searchParams.set("view", view);
  if (screen === "chat" && chatId) url.searchParams.set("chat", chatId);
  return `${url.pathname}${url.search}${url.hash}`;
}

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
      error: "Ответ для этого вопроса не сохранился. Повторите запрос.",
    });
  }
  return entries;
}

function mergeEntries(existing: Entry[], loaded: Entry[]): Entry[] {
  const known = new Set(existing.map((entry) => entry.id));
  return [...loaded.filter((entry) => !known.has(entry.id)), ...existing];
}

function AppContent({ account, onAccountChange, onLogout }: {
  account?: Account;
  onAccountChange?: (account: Account) => void;
  onLogout?: () => Promise<void>;
} = {}) {
  const { locale, setLocale, t } = useLanguage();
  const [sources, setSources] = useState<Source[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState("");
  const [postgresStatus, setPostgresStatus] = useState<PostgresStatus | null>(null);
  const [postgresLoading, setPostgresLoading] = useState(false);
  const [postgresError, setPostgresError] = useState("");
  const [sourceSetup, setSourceSetup] = useState<"csv" | "postgres">("csv");
  const [welcomeGreeting] = useState(() => welcomeGreetings[Math.floor(Math.random() * welcomeGreetings.length)]);
  const [screen, setScreen] = useState<WorkspaceScreen>(() => readWorkspaceRoute().screen);
  const initialChatId = useRef<string | null>(readWorkspaceRoute().chatId);
  const mobilePanel = screen === "home" ? "home" : screen === "chat" ? "chat" : "analytics";
  const [mobileOverlay, setMobileOverlay] = useState<"settings" | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | "system">(() => {
    const saved = localStorage.getItem("evia.theme");
    return saved === "dark" || saved === "system" ? saved : "light";
  });
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  const [selectedId, setSelectedId] = useState<string | null>(() => readWorkspaceRoute().sourceId);
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
  const [view, setViewState] = useState<View>(() => readWorkspaceRoute().view);
  const [showDashboardGallery, setShowDashboardGallery] = useState(() =>
    readWorkspaceRoute().screen === "reports");
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
  function navigateScreen(next: WorkspaceScreen, sourceId = selectedId, nextView = view, replace = false, chatId: string | null | undefined = activeConversationId) {
    setScreen(next);
    initialChatId.current = chatId ?? null;
    setShowDashboardGallery(next === "reports");
    if (next === "analysis" && sourceId) setSelectedId(sourceId);
    if (nextView) setViewState(nextView);
    setMobileOverlay(null);
    const url = workspaceUrl(next, sourceId, nextView, chatId);
    if (replace) window.history.replaceState({}, "", url);
    else if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== url)
      window.history.pushState({}, "", url);
  }
  function changeSourceView(nextView: View) {
    setViewState(nextView);
    navigateScreen("analysis", selectedId, nextView);
  }
  useEffect(() => {
    const onPopState = () => {
      const route = readWorkspaceRoute();
      setScreen(route.screen);
      initialChatId.current = route.chatId;
      setSelectedId(route.sourceId);
      setViewState(route.view);
      setShowDashboardGallery(route.screen === "reports");
      setMobileOverlay(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  useEffect(() => {
    if (sourcesLoading || !selectedId) return;
    if (!sources.some((item) => item.source_id === selectedId)) {
      setSelectedId(null);
      setScreen("home");
      setShowDashboardGallery(false);
      const url = workspaceUrl("home", null, "overview");
      window.history.replaceState({}, "", url);
    }
  }, [sources, sourcesLoading, selectedId]);
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
  useEffect(() => {
    const chatId = initialChatId.current;
    if (screen !== "chat" || !chatId || historyListLoading) return;
    const chat = chatSummaries.find((item) => item.chat_id === chatId);
    const sourceId = chat?.source_id ?? chatSources[chatId] ?? selectedId;
    if (!sourceId) {
      const archived = chatSummaries.find((item) => item.chat_id === chatId);
      if (archived) openArchivedChat(archived);
      else initialChatId.current = null;
      return;
    }
    if (selectedId !== sourceId) setSelectedId(sourceId);
    const entries = histories[sourceId] ?? [];
    if (entries.some((entry) => entry.conversationId === chatId)) {
      activeConversations.current.set(sourceId, chatId);
      setActiveIds((previous) => ({
        ...previous,
        [sourceId]: entries.filter((entry) => entry.conversationId === chatId).at(-1)?.id,
      }));
      initialChatId.current = null;
    } else {
      const activeConversation = entries.find((entry) => entry.id === activeIds[sourceId])?.conversationId;
      if (!activeConversation) activeConversations.current.set(sourceId, chatId);
      if (sources.some((item) => item.source_id === sourceId) && !loadedChats.current.has(chatId))
        void loadChatHistory(sourceId, chatId);
    }
  }, [screen, selectedId, sources, chatSummaries, chatSources, histories, activeIds, historyListLoading]);

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
    navigateScreen("analysis", id, "overview");
    setUploadFailure(null);
    setUploadError("");
    setViewState("overview");
  }
  function changeDraft(value: string) {
    if (selectedId)
      setDrafts((previous) => ({ ...previous, [selectedId]: value }));
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
    setViewState("results");
    navigateScreen("chat", null, "results", false, chat.chat_id);
    initialChatId.current = null;
    if (!loadedChats.current.has(chat.chat_id)) void loadChatHistory(key, chat.chat_id);
  }
  function openChatSummary(chat: ChatSummary) {
    const sourceId = chat.source_id ?? chatSources[chat.chat_id];
    if (!sourceId || !sources.some((item) => item.source_id === sourceId)) {
      openArchivedChat(chat);
      return;
    }
    setArchivedChatId(null);
    setSelectedId(sourceId);
    activeConversations.current.set(sourceId, chat.chat_id);
    setActiveIds((previous) => ({
      ...previous,
      [sourceId]: (histories[sourceId] ?? []).filter((entry) => entry.conversationId === chat.chat_id).at(-1)?.id,
    }));
    navigateScreen("chat", sourceId, view, false, chat.chat_id);
    if (!loadedChats.current.has(chat.chat_id)) void loadChatHistory(sourceId, chat.chat_id);
  }
  function switchChatSource(sourceId: string) {
    setArchivedChatId(null);
    if (!sourceId) {
      setSelectedId(null);
      navigateScreen("chat", null, view, false, null);
      return;
    }
    setSelectedId(sourceId);
    const conversationId = activeConversations.current.get(sourceId)
      ?? histories[sourceId]?.at(-1)?.conversationId;
    if (conversationId) {
      activeConversations.current.set(sourceId, conversationId);
      setActiveIds((previous) => ({
        ...previous,
        [sourceId]: histories[sourceId]?.filter((entry) => entry.conversationId === conversationId).at(-1)?.id,
      }));
    }
    navigateScreen("chat", sourceId, view, false, conversationId ?? null);
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
    setViewState("results");
    navigateScreen("analysis", sourceId, "results");
    if (!loadedChats.current.has(chatId)) void loadChatHistory(sourceId, chatId);
    return true;
  }
  function newAnalysis() {
    setSelectedUploadFile(null);
    setUploadError("");
    setFailedFile(null);
    setSourceSetup("csv");
    navigateScreen("home", selectedId, view);
  }
  function newDialog() {
    if (!selectedId) return;
    setActiveIds((previous) => ({ ...previous, [selectedId]: undefined }));
    activeConversations.current.delete(selectedId);
    setDrafts((previous) => ({ ...previous, [selectedId]: "" }));
    setViewState("overview");
    setShowDashboardGallery(false);
    navigateScreen("chat", selectedId, "overview", false, null);
  }
  function openMobileUpload() {
    setSelectedUploadFile(null);
    setUploadError("");
    setFailedFile(null);
    navigateScreen("home", selectedId, view);
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
    setSourceSetup("postgres");
    navigateScreen("postgres", selectedId, view);
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
    navigateScreen("home", null, "overview");
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
      navigateScreen("chat", sourceId, view, true, chatId);
      controller.signal.throwIfAborted();
      const answer = await api.chat(entry.question, sourceId, chatId, controller.signal, dashboardId, locale);
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
  function renderUploadCard() {
    return <>
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
          if (file) {
            if (window.matchMedia?.("(max-width: 640px)").matches) setSelectedUploadFile(file);
            else void upload(file);
          }
        }}
        aria-label={t("Добавление источника")}
      >
        {!sourcesLoading && <WelcomeGreeting greeting={welcomeGreeting} activeState={mascotState} />}
        <h1>{uploading ? uploadProgress === 100 ? t("Обрабатываем CSV…") : `${t("Загрузка CSV")} · ${uploadProgress ?? 0}%` : t("Добавьте CSV")}</h1>
        <p>{t("Перетащите файл сюда или выберите его с устройства")}</p>
        {selectedUploadFile && <div className="upload-selected-file">
          <Icon name="file" size={18} />
          <span>{selectedUploadFile.name}<small>{(selectedUploadFile.size / 1024).toFixed(1)} КБ</small></span>
          <Icon name="check" size={16} />
        </div>}
        {uploadError && <div className="upload-card-error"><ErrorNotice
          message={uploadError}
          onRetry={failedFile ? () => void upload(failedFile) : chooseFile}
          label={failedFile ? t("Повторить загрузку CSV") : t("Выбрать файл")}
        /></div>}
        <button
          className="primary"
          onClick={() => selectedUploadFile ? void upload(selectedUploadFile) : chooseFile()}
          disabled={uploading}
        >
          <Icon name="upload" />
          {uploading ? uploadProgress === 100 ? t("Обрабатываем…") : `${t("Загружаем")} · ${uploadProgress ?? 0}%` : selectedUploadFile ? t("Загрузить файл") : t("Выбрать CSV")}
        </button>
        <small>{t("Поддерживаются кодировки UTF-8, UTF-16 и Windows-1251")} · {t("до 512 МиБ")}</small>
      </section>
      <details className="upload-advanced"><summary>{t("Дополнительно")}</summary><p>{t("Поддерживаются UTF-8, UTF-16 и Windows-1251; разделители — запятая, точка с запятой, табуляция и вертикальная черта. Первая строка содержит уникальные названия столбцов. Для замены данных откройте «Схема» у нужного источника.")}</p></details>
    </>;
  }

  return (
    <div className={`app mobile-panel-${mobilePanel} desktop-screen-${screen}`} data-testid="app-shell" data-theme={theme === "system" ? systemDark ? "dark" : "light" : theme}>
      <a className="skip-link" href={screen === "chat" ? "#chat-workspace" : "#analysis"}>
        {t("Перейти к содержимому")}
      </a>
      <header className="topbar">
        <a
          className="brand"
          href="#analysis"
          aria-label={`EVIA, ${t("Рабочее пространство")}`}
          onClick={(event) => {
            event.preventDefault();
            navigateScreen("home", null, "overview");
          }}
        >
          EVIA
        </a>
        <nav className="workspace-nav" aria-label={t("Навигация рабочего пространства")}>
          <button aria-pressed={screen === "home"} onClick={() => navigateScreen("home", null, "overview")}><Icon name="home" size={17} />{t("Главная")}</button>
          <button aria-pressed={screen === "analysis"} disabled={!source} onClick={() => source && navigateScreen("analysis", source.source_id, view)}><Icon name="file" size={17} />{t("Анализ")}</button>
          <button aria-pressed={screen === "chat"} onClick={() => navigateScreen("chat", selectedId, view)}><Icon name="chat" size={17} />{t("Чат")}</button>
          <button aria-pressed={screen === "reports"} onClick={() => navigateScreen("reports", selectedId, view)}><Icon name="grid" size={17} />{t("Отчёты")}</button>
        </nav>
        <div className="topbar-actions">
          <button className="primary new-analysis topbar-new-analysis" onClick={newAnalysis} disabled={uploading}>
            <Icon name="plus" size={16} /> {t("Новый анализ")}
          </button>
          {account && onAccountChange && onLogout && <AccountMenu account={account} onChange={onAccountChange} onLogout={onLogout} theme={theme === "system" ? systemDark ? "dark" : "light" : theme} />}
          <button className="mobile-settings-entry" aria-label={t("Открыть настройки")} onClick={openSettings}><Icon name="settings" size={17} /><span>{t("Настройки")}</span></button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <button className="primary new-analysis" onClick={newAnalysis}>
            <Icon name="plus" />
            {t("Новый анализ")}
          </button>
          {!sourcesLoading && <div className="mobile-home-greeting"><WelcomeGreeting greeting={welcomeGreeting} activeState={mascotState} /></div>}
          <section className="nav-section">
            <div className="nav-heading">
              <h2>{t("Источники")}</h2>
              <button
                className="icon-button"
                aria-label={t("Обновить источники")}
                onClick={() => void loadSources()}
                disabled={sourcesLoading}
              >
                <Icon name="refresh" size={15} />
              </button>
            </div>
            {sourcesLoading && (
              <p className="sidebar-note" role="status">
                {t("Загружаем источники…")}
              </p>
            )}
            {sourcesError && (
              <ErrorNotice
                message={sourcesError}
                onRetry={() => void loadSources()}
              />
            )}
            {!sourcesLoading && !sourcesError && !sources.length && (
              <p className="sidebar-note">{t("Нет источников")}</p>
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
              title={t("CSV · UTF-8, UTF-16 или Windows-1251")}
              disabled={uploading}
            >
              <Icon name="plus" size={16} />
              {uploading ? uploadProgress === 100 ? t("Обрабатываем CSV…") : `${t("Загружаем CSV")} · ${uploadProgress ?? 0}%` : t("Добавить CSV")}
            </button>
            <button
              className={`postgres-nav ${!source && sourceSetup === "postgres" ? "selected" : ""}`}
              onClick={openPostgresSetup}
              aria-pressed={!source && sourceSetup === "postgres"}
              title={postgresStatus?.connected ? "PostgreSQL доступен" : undefined}
            >
              {t("Подключить PostgreSQL")}
            </button>
          </section>
          <button className={`reports-nav ${showDashboardGallery ? "selected" : ""}`} type="button" aria-pressed={showDashboardGallery} onClick={() => navigateScreen("reports", selectedId, view)}>
            {t("Сохранённые отчёты")} <Icon name="chevron" size={15} />
          </button>
          <section className="nav-section history-section">
            <div className="nav-heading">
              <h2>{t("История диалогов")}</h2>
              {historyCount > 0 && (
                <span className="nav-count">{historyCount}</span>
              )}
            </div>
            {historyListLoading ? (
              <p className="sidebar-note" role="status">{t("Загружаем диалоги…")}</p>
            ) : historyListError ? (
              <ErrorNotice
                message={historyListError}
                onRetry={() => void loadChatList()}
                label={t("Повторить загрузку диалогов")}
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
                      setViewState("results");
                      navigateScreen("analysis", selectedId, "results");
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
                    title={`${t("Источник недоступен")} · ${chat.title}`}
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
                    title={`${t("Без источника")} · ${chat.title}`}
                    onClick={() => openArchivedChat(chat)}
                  >
                    <Icon name="chat" size={16} />
                    <span>{chat.title}</span>
                  </button>
                ))}
              </div>
                ) : !failedServerChat && (
                  <p className="sidebar-note">{t("Нет диалогов")}</p>
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
          <input
            className="visually-hidden"
            type="file"
            accept=".csv,text/csv"
            aria-label={t("Загрузить CSV")}
            ref={fileInput}
            tabIndex={-1}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                if (window.matchMedia?.("(max-width: 640px)").matches) setSelectedUploadFile(file);
                else void upload(file);
              }
              event.target.value = "";
            }}
          />
          <div className="mobile-page-header">
            <button aria-label={t("Назад к источникам")} onClick={() => navigateScreen("home", null, "overview")}>
              <Icon name="back" size={22} />
            </button>
            <strong>{showDashboardGallery ? t("Отчёты") : source ? t("Данные источника") : sourceSetup === "postgres" ? "PostgreSQL" : t("Данные")}</strong>
            <span aria-hidden="true" />
          </div>
          {screen === "home" ? (
            <HomePage
              sources={sources}
              selectedSourceId={selectedId}
              chats={chatSummaries}
              loading={sourcesLoading}
              error={sourcesError}
              uploadCard={renderUploadCard()}
              onRefresh={() => void loadSources()}
              onSelectSource={selectSource}
              onPostgres={openPostgresSetup}
              onReports={() => navigateScreen("reports", selectedId, view)}
              onOpenChat={openChatSummary}
              chatLoading={historyListLoading}
              chatError={historyListError}
              onRefreshChats={() => void loadChatList()}
            />
          ) : screen === "reports" ? (
            <DashboardGallery onClose={() => navigateScreen(source ? "analysis" : "home", source?.source_id ?? null, view)} onOpenOrigin={openDashboardOrigin} onAttach={source ? (id, title) => {
              setAttachedDashboard({ id, title });
              navigateScreen("chat", selectedId, view);
            } : undefined} />
          ) : screen === "analysis" && source ? (
            <SourceInspector
              source={source}
              entry={activeEntry}
              reportEntries={history}
              view={view}
              setView={changeSourceView}
              onOpenChat={() => navigateScreen("chat", selectedId, view)}
              onReimport={(file, id) => void upload(file, id)}
              onDelete={deleteSource}
              deleteDisabled={uploading || Boolean(pending)}
            />
          ) : screen === "analysis" && !source ? (
            <div className="home-empty" role={sourcesLoading ? "status" : undefined}>
              <strong>{sourcesLoading ? t("Загружаем источник…") : t("Источник недоступен")}</strong>
              {!sourcesLoading && <button className="text-button" onClick={() => navigateScreen("home", null, "overview")}>{t("Вернуться к источникам")}</button>}
            </div>
          ) : screen === "postgres" ? (
            <PostgresSetup
              status={postgresStatus}
              loading={postgresLoading}
              error={postgresError}
              sources={postgresSources}
              onRetry={() => void refreshPostgres()}
              onSelect={selectSource}
            />
          ) : null}
        </main>
        <aside id="chat-workspace" className="chat-panel" aria-label={t("Чат с EVIA")}>
          <header className="chat-header">
            <div className="chat-title"><h2>{t("AI-помощник")}</h2><strong className="mobile-chat-brand">EVIA</strong></div>
            <label className="chat-source-picker">
              <Icon name="file" size={15} />
              <span className="visually-hidden">{t("Источник данных для чата")}</span>
              <select aria-label={t("Источник данных для чата")} value={selectedId ?? ""} onChange={(event) => switchChatSource(event.target.value)}>
                <option value="">{t("Без источника")}</option>
                {sources.map((item) => <option key={item.source_id} value={item.source_id}>{item.name}</option>)}
              </select>
            </label>
            {source && <button className="new-dialog" type="button" onClick={newDialog}><Icon name="plus" size={15} /> {t("Новый диалог")}</button>}
          </header>
          <div className="chat-content">
            {activeEntry ? (
              <>
              {activePage?.hasMore && (
                <div className="history-pagination">
                  {activePage.loading ? (
                    <p role="status">{t("Загружаем предыдущие сообщения…")}</p>
                  ) : activePage.error ? (
                    <ErrorNotice
                      message={activePage.error}
                      onRetry={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
                    label={t("Повторить загрузку истории")}
                    />
                  ) : (
                    <button
                      className="text-button"
                      onClick={() => historyKey && activePage.nextBefore !== null && void loadChatHistory(historyKey, activeConversationId!, activePage.nextBefore)}
                    >
                      {t("Показать предыдущие сообщения")}
                    </button>
                  )}
                </div>
              )}
              {conversationEntries.map((message) => <article key={message.id} className="chat-turn">
                <div className="user-message">{message.question}</div>
                <section className="assistant-message" aria-label={t("Ответ EVIA")}>
                  <div className="reply-label">EVIA</div>
                  {message.state === "pending" ? (
                    <div className="thinking" role="status">
                      <span />
                      <span />
                      <span />
                      <p>{t("Изучаю ваш вопрос…")}</p>
                    </div>
                  ) : message.state === "error" ? (
                    <ErrorNotice
                      message={
                        t(message.error ?? "Не удалось получить ответ.")
                      }
                      onRetry={() =>
                        void send(message.question, message.id)
                      }
                      label={t("Повторить вопрос")}
                    />
                  ) : (
                    <>
                      <SafeMarkdown>
                        {message.answer?.answer || t("Модель вернула пустой ответ.")}
                      </SafeMarkdown>
                      {message.answer?.clarification?.options && (
                        <div className="clarification-options" aria-label={t("Варианты уточнения")}>
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
                            ? t("Это старый текстовый ответ: SQL, таблица и время тогда не сохранялись.")
                            : message.historyDetail === "unsupported"
                              ? t("Сохранённые детали созданы более новой версией EVIA и пока показаны только текстом.")
                              : t("Сохранённые детали этого ответа повреждены, поэтому показан только текст.")}
                        </p>
                      )}
                      {!message.historyDetail && Boolean(message.answer?.tool_results.length || message.answer?.analysis?.sql) && <button
                        className="result-link"
                        onClick={() => {
                          if (historyKey) setActiveIds((previous) => ({ ...previous, [historyKey]: message.id }));
                          setViewState("results");
                          navigateScreen("analysis", selectedId, "results");
                        }}
                      >
                        {t("Открыть результат")}
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
                <h3>{t(source ? "Спросите о своих данных" : "Добавьте источник данных")}</h3>
                <p className="mobile-chat-intro">{t(source ? "EVIA поможет найти ответ, построить график или разобраться в таблице." : "Загрузите CSV или подключите PostgreSQL, чтобы начать анализ.")}</p>
                <p
                  className={`evia-live-status ${["welcome", "waiting", "listening", "explaining"].includes(mascotState) ? "visually-hidden" : ""}`}
                  role="status"
                >
                  {t(eviaStatus(mascotState))}
                </p>
                {source && (
                  <div className="suggestions">
                    {[
                      t("Какие есть столбцы?"),
                      t("Покажи первые строки"),
                      t("Есть ли пропуски?"),
                      t("Построй график распределения"),
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
            {attachedDashboard && source && <div className="attached-report" aria-label={t("Прикреплённый отчёт")}><span>{t("Отчёт:")} <strong>{attachedDashboard.title}</strong></span><button type="button" aria-label={t("Открепить отчёт")} onClick={() => setAttachedDashboard(null)}><Icon name="close" size={14} /></button></div>}
            {activeEntry && <div className="helper" role="status"><Evia state={mascotState} />{activeEntry.state === "pending" && <strong>{t(eviaStatus(mascotState))}</strong>}</div>}
            {archivedChat && !archivedChat.source_id && (
              <p className="history-details-notice">
                {t("Для продолжения этого старого диалога выберите источник в левой панели.")}
              </p>
            )}
            <form className="composer" onSubmit={submit}>
              <label className="visually-hidden" htmlFor="question">
                {t("Ваш вопрос")}
              </label>
              <textarea
                id="question"
                ref={composer}
                placeholder={
                  source
                    ? t("Что хотите узнать о данных?")
                    : t("Сначала добавьте источник…")
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
                    t("Источник не выбран")
                  )}
                </span>
                {pending ? (
                  <button
                    type="button"
                    className="stop-button"
                    aria-label={t("Прекратить ожидание")}
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
                    aria-label={t("Отправить вопрос")}
                    disabled={
                      !source || !draft.trim() || draft.trim().length > 4000
                    }
                  >
                    <Icon name="arrow" />
                  </button>
                )}
              </div>
            </form>
            {source && <div className="mobile-chat-source" aria-label={t("Прикреплённый источник")}><Icon name="file" size={14} /><span>{source.name}{source.source_type === "csv" && !source.name.toLowerCase().endsWith(".csv") ? ".csv" : ""}</span><button type="button" aria-label={t("Убрать источник из чата")} onClick={() => setSelectedId(null)}><Icon name="close" size={14} /></button></div>}
            <div className="composer-hint">
              <span>{t("Ctrl / ⌘ + Enter — отправить")}</span>
              {draft.length > 3500 && <span>{draft.length}/4000</span>}
            </div>
          </div>
        </aside>
      </div>
      {mobileOverlay === "settings" && <div className="settings-backdrop" data-testid="settings-backdrop" aria-hidden="true" onClick={() => setMobileOverlay(null)} />}
      {mobileOverlay === "settings" && <section className="mobile-fullscreen mobile-settings" role="dialog" aria-label={t("Настройки")} aria-modal="true" ref={settingsDialog}>
        <header><h2>{t("Настройки")}</h2><button aria-label={t("Закрыть настройки")} onClick={() => setMobileOverlay(null)}><Icon name="close" size={19} /></button></header>
        <h3>{t("Тема")}</h3>
        <div className="settings-options">
          {([ ["light", "Светлая"], ["dark", "Тёмная"], ["system", "Системная"] ] as const).map(([value, label]) => <button key={value} aria-label={locale === "en" ? `${t(label)} theme` : `${label} тема`} aria-pressed={theme === value} onClick={() => chooseTheme(value)}><span>{t(label)}</span>{theme === value && <Icon name="check" size={16} />}</button>)}
        </div>
        <label className="settings-info language-setting"><span>{t("Язык")}</span><select aria-label={t("Язык")} value={locale} onChange={(event) => setLocale(event.target.value as "ru" | "en")}><option value="ru">{t("Русский")}</option><option value="en">{t("Английский")}</option></select></label>
      </section>}
      <nav className="mobile-nav" aria-label={t("Мобильная навигация")}>
        <button
          aria-label={t("Источники")}
          aria-pressed={mobilePanel === "home"}
          onClick={() => navigateScreen("home", null, "overview")}
        >
          <Icon name="home" size={18} />
          <span>{t("Источники")}</span>
        </button>
        <button
          aria-label={t("Рабочее пространство")}
          aria-pressed={mobilePanel === "analytics"}
          onClick={() => source ? navigateScreen("analysis", source.source_id, view) : navigateScreen("reports", null, view)}
        >
          <Icon name="file" size={18} />
          <span>{t("Данные")}</span>
        </button>
        <button
          aria-label={t("Чат")}
          aria-pressed={mobilePanel === "chat"}
          onClick={() => navigateScreen("chat", selectedId, view)}
        >
          <Icon name="chat" size={18} />
          <span>{t("Чат")}</span>
        </button>
        <button
          aria-label={t("Настройки")}
          aria-pressed={mobileOverlay === "settings"}
          onClick={openSettings}
        >
          <Icon name="settings" size={18} />
          <span>{t("Настройки")}</span>
        </button>
      </nav>
    </div>
  );
}

export default function App(props: {
  account?: Account;
  onAccountChange?: (account: Account) => void;
  onLogout?: () => Promise<void>;
} = {}) {
  return <LanguageProvider><AppContent {...props} /></LanguageProvider>;
}
