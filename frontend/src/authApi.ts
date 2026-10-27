export type Account = { id: string; email: string; name: string; created_at: string };
export type AuthStatus = { enabled: boolean; recovery_available: boolean };

async function call<T>(url: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string"
      ? data.detail : `Ошибка сервера (${response.status})`;
    throw Object.assign(new Error(detail), { status: response.status });
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const authApi = {
  status: () => call<AuthStatus>("/auth/status"),
  me: () => call<Account>("/auth/me"),
  register: (email: string, password: string, name: string) => call<Account>("/auth/register", "POST", { email, password, name }),
  login: (email: string, password: string) => call<Account>("/auth/login", "POST", { email, password }),
  logout: () => call<void>("/auth/logout", "POST"),
  rename: (name: string) => call<Account>("/auth/profile", "PATCH", { name }),
  password: (current_password: string, new_password: string) => call<{ ok: boolean }>("/auth/password", "POST", { current_password, new_password }),
  resetRequest: (email: string) => call<{ ok: boolean }>("/auth/reset/request", "POST", { email }),
  resetConfirm: (email: string, code: string, new_password: string) => call<{ ok: boolean }>("/auth/reset/confirm", "POST", { email, code, new_password }),
};
