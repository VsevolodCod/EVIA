import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AuthGate from "./AuthGate";
import { LanguageProvider } from "./language";

vi.mock("./App", () => ({ default: ({ account }: { account?: { name: string } }) => <div>Рабочее пространство {account?.name}</div> }));

test("a visitor can switch the sign-in form to English", async () => {
  localStorage.removeItem("evia.language");
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url === "/auth/status"
    ? Response.json({ enabled: true, recovery_available: true })
    : Response.json({ detail: "Sign in required" }, { status: 401 }))));
  try {
    render(<LanguageProvider><AuthGate /></LanguageProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "English" }));
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  } finally {
    localStorage.removeItem("evia.language");
    vi.unstubAllGlobals();
  }
});

test("a visitor registers, enters the workspace, and sees the profile", async () => {
  const fetcher = vi.fn((url: string) => {
    if (url === "/auth/status") return Promise.resolve(Response.json({ enabled: true, recovery_available: false }));
    if (url === "/auth/me") return Promise.resolve(Response.json({ detail: "Sign in required" }, { status: 401 }));
    if (url === "/auth/register") return Promise.resolve(Response.json({
      id: "user-1", email: "person@example.com", name: "Саша", created_at: "2026-10-27T00:00:00Z",
    }, { status: 201 }));
    throw new Error(`Unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AuthGate />);
  fireEvent.click(await screen.findByRole("button", { name: "Регистрация" }));
  expect(screen.queryByText("Ваши источники, диалоги и дашборды будут доступны только вам.")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Саша" } });
  fireEvent.change(screen.getByLabelText("Почта"), { target: { value: "person@example.com" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "strong password 123" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать аккаунт" }));
  await waitFor(() => expect(screen.getByText("Рабочее пространство Саша")).toBeInTheDocument());
});
