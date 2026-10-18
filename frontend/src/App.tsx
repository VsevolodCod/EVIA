import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, waitForChat, errorMessage, type Health, type Source } from "./api";
import { ErrorNotice, Evia, Icon, SafeMarkdown } from "./components";
import { SourceInspector } from "./features/sources/SourceInspector";
import type { Entry, View } from "./features/chat/types";
import { ResponseTiming } from "./features/chat/ResponseTiming";
import "./styles.css";
import {
  resolveEviaState,
  errorEviaState,
  eviaStatus,
} from "./features/mascot/resolveEviaState";
import type { EviaState } from "./features/mascot/states";

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [histories, setHistories] = useState<Record<string, Entry[]>>({});
  const [activeIds, setActiveIds] = useState<
    Record<string, string | undefined>
  >({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [view, setView] = useState<View>("overview");
  const [quiet, setQuiet] = useState(() => {
    try {
      return localStorage.getItem("linza.quiet") === "true";
    } catch {
      return false;
    }
  });
  const [uploadedId, setUploadedId] = useState<string | null>(null);
  const [uploadFailure, setUploadFailure] = useState<EviaState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const sourceController = useRef<AbortController | null>(null);
  const healthController = useRef<AbortController | null>(null);
  const uploadController = useRef<AbortController | null>(null);
  const askControllers = useRef(new Map<string, AbortController>());
  const activeConversations = useRef(new Map<string, string>());
  const serverChats = useRef(new Map<string, Promise<string>>());
  const sequence = useRef(0);
  const mounted = useRef(true);
  const source = sources.find((item) => item.source_id === selectedId);
  const history = selectedId ? (histories[selectedId] ?? []) : [];
  const activeEntry = history.find(
    (entry) => entry.id === (selectedId ? activeIds[selectedId] : undefined),
  );
  const conversationEntries = activeEntry
    ? history.filter((entry) => entry.conversationId === activeEntry.conversationId)
    : [];
  const conversations = history.filter((entry, index) =>
    history.findIndex((item) => item.conversationId === entry.conversationId) === index);
  const pending = conversationEntries.find((entry) => entry.state === "pending");
  const draft = selectedId ? (drafts[selectedId] ?? "") : "";
  const mascotState = resolveEviaState({
    uploading,
    uploadFailure,
    request: pending ? (pending.mascotState ?? "thinking") : undefined,
    connectionFailure: Boolean(healthError || sourcesError),
    selectedId,
    uploadedId,
    draft,
    entry: activeEntry,
  });
  const isMock = health?.llm_provider === "mock";

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
  async function loadHealth() {
    healthController.current?.abort();
    const controller = new AbortController();
    healthController.current = controller;
    setHealthError("");
    try {
      const result = await api.health(controller.signal);
      if (!controller.signal.aborted) setHealth(result);
    } catch (error) {
      if (!controller.signal.aborted) {
        setHealth(null);
        setHealthError(errorMessage(error));
      }
    }
  }
  useEffect(() => {
    mounted.current = true;
    void loadSources();
    void loadHealth();
    return () => {
      mounted.current = false;
      sourceController.current?.abort();
      healthController.current?.abort();
      uploadController.current?.abort();
      askControllers.current.forEach((controller) => controller.abort());
    };
  }, []);

  function selectSource(id: string) {
    setSelectedId(id);
    setUploadFailure(null);
    setUploadError("");
    setView("overview");
  }
  function changeDraft(value: string) {
    if (selectedId)
      setDrafts((previous) => ({ ...previous, [selectedId]: value }));
  }
  function newAnalysis() {
    if (!selectedId) {
      fileInput.current?.click();
      return;
    }
    setActiveIds((previous) => ({ ...previous, [selectedId]: undefined }));
    activeConversations.current.delete(selectedId);
    changeDraft("");
    setUploadedId(null);
    setUploadFailure(null);
    setUploadError("");
    setView("overview");
    composer.current?.focus();
  }
  function toggleQuiet() {
    const next = !quiet;
    setQuiet(next);
    try {
      localStorage.setItem("linza.quiet", String(next));
    } catch {
      /* The preference still works for this session. */
    }
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
      let chat = serverChats.current.get(conversationId);
      if (!chat) {
        chat = api.createChat(entry.question.slice(0, 200)).then((result) => result.chat_id);
        serverChats.current.set(conversationId, chat);
        chat.catch(() => serverChats.current.delete(conversationId));
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
    <div className={`app ${quiet ? "quiet" : ""}`}>
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
        <div
          className="connection"
          title={
            isMock
              ? "Ответы тестовые: аналитическая модель не подключена"
              : undefined
          }
        >
          {health ? (
            <>
              <span className="status-dot" />
              {isMock ? "Тестовая модель" : `Модель: ${health.llm_provider}`}
            </>
          ) : healthError ? (
            <button
              className="text-button connection-error"
              onClick={() => void loadHealth()}
            >
              <Icon name="refresh" />
              Проверить соединение
            </button>
          ) : (
            <span>Подключаемся…</span>
          )}
        </div>
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
            {history.length ? (
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
          <div className="sidebar-bottom">
            <button
              className="quiet-button"
              aria-pressed={quiet}
              onClick={toggleQuiet}
            >
              <Icon name="quiet" />
              Тихий режим
              <span className="toggle">
                <span />
              </span>
            </button>
          </div>
        </aside>
        <main
          className={`analysis ${source ? "" : "analysis-empty"}`}
          id="analysis"
          tabIndex={-1}
        >
          {healthError && (
            <ErrorNotice
              message={healthError}
              onRetry={() => void loadHealth()}
              label="Проверить сервис"
            />
          )}
          {source ? (
            <SourceInspector
              source={source}
              entry={activeEntry}
              view={view}
              setView={setView}
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
                <Evia large state={mascotState} quiet={quiet} />
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
                <Evia state={mascotState} quiet={quiet} />
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
                сообщения. «Новый анализ» начинает отдельный диалог. У каждого
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
