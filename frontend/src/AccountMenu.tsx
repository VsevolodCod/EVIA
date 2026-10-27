import { useState, type FormEvent } from "react";
import { authApi, type Account } from "./authApi";

export function AccountMenu({ account, onChange, onLogout }: {
  account: Account;
  onChange: (account: Account) => void;
  onLogout: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(account.name);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveName(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try { onChange(await authApi.rename(name)); setNotice("Имя сохранено."); }
    catch (err) { setError(err instanceof Error ? err.message : "Не удалось сохранить имя."); }
    finally { setBusy(false); }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      await authApi.password(currentPassword, newPassword);
      setCurrentPassword(""); setNewPassword(""); setNotice("Пароль обновлён.");
    } catch (err) { setError(err instanceof Error ? err.message : "Не удалось сменить пароль."); }
    finally { setBusy(false); }
  }

  return <div className="account-menu">
    <button className="account-trigger" aria-label="Открыть профиль" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span className="account-avatar">{account.name.trim().charAt(0).toUpperCase()}</span><span className="account-name">{account.name}</span>
    </button>
    {open && <section className="account-popover" role="dialog" aria-label="Профиль">
      <div className="account-heading"><h2>Профиль</h2><button aria-label="Закрыть профиль" onClick={() => setOpen(false)}>×</button></div>
      <p className="account-email">{account.email}</p>
      <form onSubmit={(event) => void saveName(event)}><label>Имя<input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} required /></label><button disabled={busy || name.trim() === account.name}>Сохранить имя</button></form>
      <form onSubmit={(event) => void savePassword(event)}><label>Текущий пароль<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label><label>Новый пароль<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={12} required /></label><button disabled={busy}>Сменить пароль</button></form>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {notice && <p className="auth-notice" role="status">{notice}</p>}
      <button className="account-logout" onClick={() => void onLogout()}>Выйти</button>
    </section>}
  </div>;
}
