import { useEffect, useState, type FormEvent } from "react";
import App from "./App";
import { authApi, type Account, type AuthStatus } from "./authApi";
import "./auth.css";
import { LanguageSwitch, useLanguage } from "./language";

type Mode = "login" | "register" | "reset-request" | "reset-confirm";

export default function AuthGate() {
  const { t } = useLanguage();
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
            setError(t("Не удалось проверить вход. Обновите страницу.", "Could not verify your session. Refresh the page."));
        }
      }
    }).catch(() => { if (alive) setError(t("Не удалось связаться с сервером. Обновите страницу.", "Could not reach the server. Refresh the page.")); })
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
        setNotice(t("Если аккаунт существует, код отправлен на почту.", "If the account exists, a code has been sent to its email address."));
      } else {
        await authApi.resetConfirm(email, code, password);
        setMode("login");
        setPassword("");
        setNotice(t("Пароль обновлён. Теперь войдите.", "Password updated. You can now sign in."));
      }
    } catch (err) {
      const details = err instanceof Error ? err.message : t("Попробуйте ещё раз.", "Please try again.");
      const messages: Record<string, string> = {
        "Invalid email or password": t("Неверная почта или пароль.", "Incorrect email or password."),
        "Email already registered": t("Эта почта уже зарегистрирована.", "This email is already registered."),
        "Code is invalid or expired": t("Код неверен или срок действия истёк.", "The code is invalid or has expired."),
        "Password must contain 12–128 characters": t("Пароль должен содержать от 12 до 128 символов.", "Password must contain 12–128 characters."),
      };
      setError(messages[details] ?? details);
    } finally {
      setBusy(false);
    }
  }

  if (checking) return <div className="auth-loading" role="status">{t("Проверяем вход…", "Checking your session…")}</div>;
  if (!status) return <div className="auth-loading" role="alert">{error || t("Не удалось загрузить вход.", "Could not load sign in.")} <button onClick={() => window.location.reload()}>{t("Повторить", "Retry")}</button></div>;
  if (!status.enabled) return <App />;
  if (account) return <App key={account.id} account={account} onAccountChange={setAccount} onLogout={async () => {
    await authApi.logout();
    localStorage.removeItem("evia.chat-sources.v1");
    setAccount(null);
  }} />;

  return <main className="auth-page">
    <div className="auth-brand">EVIA</div>
    <section className="auth-card" aria-label={t("Вход в EVIA", "Sign in to EVIA")}>
      <h1>{mode === "login" ? t("Вход", "Sign in") : mode === "register" ? t("Создать аккаунт", "Create account") : t("Восстановить пароль", "Reset password")}</h1>
      <LanguageSwitch />
      {mode !== "reset-request" && mode !== "reset-confirm" && <div className="auth-tabs">
        <button type="button" aria-pressed={mode === "login"} onClick={() => { setMode("login"); setError(""); }}>{t("Вход", "Sign in")}</button>
        <button type="button" aria-pressed={mode === "register"} onClick={() => { setMode("register"); setError(""); }}>{t("Регистрация", "Sign up")}</button>
      </div>}
      <form onSubmit={(event) => void submit(event)}>
        {mode === "register" && <label>{t("Имя", "Name")}<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required maxLength={80} /></label>}
        <label>{t("Почта", "Email")}<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label>
        {mode === "reset-confirm" && <label>{t("Код из письма", "Email code")}<input inputMode="numeric" pattern="[0-9]{8}" maxLength={8} value={code} onChange={(event) => setCode(event.target.value)} required /></label>}
        {mode !== "reset-request" && <label>{mode === "reset-confirm" ? t("Новый пароль", "New password") : t("Пароль", "Password")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "login" ? 1 : 12} required /></label>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {notice && <p className="auth-notice" role="status">{notice}</p>}
        <button className="auth-submit" disabled={busy}>{busy ? t("Подождите…", "Please wait…") : mode === "login" ? t("Войти", "Sign in") : mode === "register" ? t("Создать аккаунт", "Create account") : mode === "reset-request" ? t("Отправить код", "Send code") : t("Обновить пароль", "Update password")}</button>
      </form>
      {mode === "login" && <button className="auth-link" disabled={!status.recovery_available} title={!status.recovery_available ? t("Отправка писем пока не настроена", "Email delivery is not configured") : undefined} onClick={() => setMode("reset-request")}>{t("Забыли пароль?", "Forgot password?")}</button>}
      {(mode === "reset-request" || mode === "reset-confirm") && <button className="auth-link" onClick={() => { setMode("login"); setError(""); }}>{t("Вернуться ко входу", "Back to sign in")}</button>}
      {!status.recovery_available && <p className="auth-hint">{t("Восстановление по почте станет доступно после настройки отправки писем.", "Password recovery will be available when email delivery is configured.")}</p>}
    </section>
  </main>;
}
