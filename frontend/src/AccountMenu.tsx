import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./components/Icon";
import { authApi, type Account } from "./authApi";
import { useLanguage } from "./language";

export function AccountMenu({ account, onChange, onLogout, theme = "light" }: {
  account: Account;
  onChange: (account: Account) => void;
  onLogout: () => Promise<void>;
  theme?: "light" | "dark";
}) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(account.name);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.querySelector<HTMLButtonElement>(".account-close")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled])"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!dialog.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      trigger.current?.focus();
    };
  }, [open]);

  async function saveName(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try { onChange(await authApi.rename(name)); setNotice(t("Имя сохранено.", "Name saved.")); }
    catch (err) { setError(err instanceof Error ? err.message : t("Не удалось сохранить имя.", "Could not save name.")); }
    finally { setBusy(false); }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      await authApi.password(currentPassword, newPassword);
      setCurrentPassword(""); setNewPassword(""); setNotice(t("Пароль обновлён.", "Password updated."));
    } catch (err) { setError(err instanceof Error ? err.message : t("Не удалось сменить пароль.", "Could not change password.")); }
    finally { setBusy(false); }
  }

  async function uploadPhoto(file?: File) {
    if (!file) return;
    setError(""); setNotice("");
    if (file.size > 1_048_576) { setError(t("Фотография должна быть меньше 1 МБ.", "Photo must be smaller than 1 MB.")); return; }
    setBusy(true);
    try { onChange(await authApi.uploadAvatar(file)); setNotice(t("Фотография сохранена.", "Photo saved.")); }
    catch (err) { setError(err instanceof Error ? err.message : t("Не удалось загрузить фотографию.", "Could not upload photo.")); }
    finally { setBusy(false); }
  }

  async function removePhoto() {
    setBusy(true); setError(""); setNotice("");
    try { onChange(await authApi.removeAvatar()); setNotice(t("Фотография удалена.", "Photo removed.")); }
    catch (err) { setError(err instanceof Error ? err.message : t("Не удалось удалить фотографию.", "Could not remove photo.")); }
    finally { setBusy(false); }
  }

  return <>
    <div className="account-menu">
      <button ref={trigger} type="button" className="account-trigger" aria-label={t("Открыть профиль", "Open profile")} aria-expanded={open} onClick={() => setOpen(true)}>
        {account.avatar_url ? <img className="account-avatar-image" src={account.avatar_url} alt="" /> : <Icon name="user" size={20} />}
      </button>
    </div>
    {open && createPortal(<>
      <div className="account-backdrop" aria-hidden="true" onClick={() => setOpen(false)} />
      <section ref={dialog} className="account-popover" data-theme={theme} role="dialog" aria-label={t("Профиль", "Profile")} aria-modal="true">
        <div className="account-heading"><h2>{t("Профиль", "Profile")}</h2><button type="button" className="account-close" aria-label={t("Закрыть профиль", "Close profile")} onClick={() => setOpen(false)}>×</button></div>
        <div className="account-identity">
          <span className="account-avatar-large">{account.avatar_url ? <img src={account.avatar_url} alt="" /> : <Icon name="user" size={32} />}</span>
          <div><strong>{account.name}</strong><p className="account-email">{account.email}</p></div>
        </div>
        <div className="account-photo-actions">
          <label className="account-photo-upload">{t("Выбрать фотографию", "Choose photo")}<input type="file" aria-label={t("Фотография профиля", "Profile photo")} accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(event) => { void uploadPhoto(event.target.files?.[0]); event.target.value = ""; }} /></label>
          {account.avatar_url && <button type="button" disabled={busy} onClick={() => void removePhoto()}>{t("Удалить фото", "Remove photo")}</button>}
        </div>
        <form onSubmit={(event) => void saveName(event)}><label>{t("Имя", "Name")}<input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} required /></label><button disabled={busy || name.trim() === account.name}>{t("Сохранить имя", "Save name")}</button></form>
        <form onSubmit={(event) => void savePassword(event)}><label>{t("Текущий пароль", "Current password")}<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label><label>{t("Новый пароль", "New password")}<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={12} required /></label><button disabled={busy}>{t("Сменить пароль", "Change password")}</button></form>
        {error && <p className="auth-error" role="alert">{error}</p>}
        {notice && <p className="auth-notice" role="status">{notice}</p>}
        <button className="account-logout" onClick={() => void onLogout()}>{t("Выйти", "Sign out")}</button>
      </section>
    </>, document.body)}
  </>;
}
