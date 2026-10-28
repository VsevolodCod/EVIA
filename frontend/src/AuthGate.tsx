import { useEffect, useState, type FormEvent } from "react";
import App from "./App";
import { authApi, type Account, type AuthStatus } from "./authApi";
import "./auth.css";

type Mode = "login" | "register" | "reset-request" | "reset-confirm";

export default function AuthGate() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [checking, setChecking] = useState(true);
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let alive = true;
    authApi.status().then(async (result) => {
      if (!alive) return;
      setStatus(result);
      if (result.enabled) {
        try {
          const user = await authApi.me();
          if (alive) setAccount(user);
        } catch (err) {
          if (alive && !(err instanceof Error && "status" in err && err.status === 401))
            setError("Не удалось проверить вход. Обновите страницу.");
        }
      }
    }).catch(() => { if (alive) setError("Не удалось связаться с сервером. Обновите страницу."); })
      .finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const expired = () => {
      localStorage.removeItem("evia.chat-sources.v1");
      setAccount(null);
    };
    window.addEventListener("evia:unauthorized", expired);
    return () => window.removeEventListener("evia:unauthorized", expired);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (mode === "login") setAccount(await authApi.login(email, password));
      else if (mode === "register") setAccount(await authApi.register(email, password, name));
      else if (mode === "reset-request") {
        await authApi.resetRequest(email);
        setMode("reset-confirm");
        setNotice("Если аккаунт существует, код отправлен на почту.");
      } else {
        await authApi.resetConfirm(email, code, password);
        setMode("login");
        setPassword("");
        setNotice("Пароль обновлён. Теперь войдите.");
      }
    } catch (err) {
      const details = err instanceof Error ? err.message : "Попробуйте ещё раз.";
      const messages: Record<string, string> = {
        "Invalid email or password": "Неверная почта или пароль.",
        "Email already registered": "Эта почта уже зарегистрирована.",
        "Code is invalid or expired": "Код неверен или срок действия истёк.",
        "Password must contain 12–128 characters": "Пароль должен содержать от 12 до 128 символов.",
      };
      setError(messages[details] ?? details);
    } finally {
      setBusy(false);
    }
  }

  if (checking) return <div className="auth-loading" role="status">Проверяем вход…</div>;
  if (!status) return <div className="auth-loading" role="alert">{error || "Не удалось загрузить вход."} <button onClick={() => window.location.reload()}>Повторить</button></div>;
  if (!status.enabled) return <App />;
  if (account) return <App key={account.id} account={account} onAccountChange={setAccount} onLogout={async () => {
    await authApi.logout();
    localStorage.removeItem("evia.chat-sources.v1");
    setAccount(null);
  }} />;

  return <main className="auth-page">
    <div className="auth-brand">EVIA</div>
    <section className="auth-card" aria-label="Вход в EVIA">
      <h1>{mode === "login" ? "Вход" : mode === "register" ? "Создать аккаунт" : "Восстановить пароль"}</h1>
      {mode !== "reset-request" && mode !== "reset-confirm" && <div className="auth-tabs">
        <button type="button" aria-pressed={mode === "login"} onClick={() => { setMode("login"); setError(""); }}>Вход</button>
        <button type="button" aria-pressed={mode === "register"} onClick={() => { setMode("register"); setError(""); }}>Регистрация</button>
      </div>}
      <form onSubmit={(event) => void submit(event)}>
        {mode === "register" && <label>Имя<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required maxLength={80} /></label>}
        <label>Почта<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label>
        {mode === "reset-confirm" && <label>Код из письма<input inputMode="numeric" pattern="[0-9]{8}" maxLength={8} value={code} onChange={(event) => setCode(event.target.value)} required /></label>}
        {mode !== "reset-request" && <label>{mode === "reset-confirm" ? "Новый пароль" : "Пароль"}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "login" ? 1 : 12} required /></label>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {notice && <p className="auth-notice" role="status">{notice}</p>}
        <button className="auth-submit" disabled={busy}>{busy ? "Подождите…" : mode === "login" ? "Войти" : mode === "register" ? "Создать аккаунт" : mode === "reset-request" ? "Отправить код" : "Обновить пароль"}</button>
      </form>
      {mode === "login" && <button className="auth-link" disabled={!status.recovery_available} title={!status.recovery_available ? "Отправка писем пока не настроена" : undefined} onClick={() => setMode("reset-request")}>Забыли пароль?</button>}
      {(mode === "reset-request" || mode === "reset-confirm") && <button className="auth-link" onClick={() => { setMode("login"); setError(""); }}>Вернуться ко входу</button>}
      {!status.recovery_available && <p className="auth-hint">Восстановление по почте станет доступно после настройки отправки писем.</p>}
    </section>
  </main>;
}
