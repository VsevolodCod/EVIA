import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AccountMenu } from "./AccountMenu";

it("opens a modal profile and uploads the owner's photo", async () => {
  const onChange = vi.fn();
  const onLogout = vi.fn(async () => {});
  const fetcher = vi.fn(async (url: string) => {
    if (url === "/auth/avatar") return Response.json({
      id: "owner", email: "owner@example.com", name: "Owner", created_at: "2026-10-28T00:00:00Z",
      avatar_url: "/auth/avatar?v=1",
    });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountMenu account={{ id: "owner", email: "owner@example.com", name: "Owner", created_at: "2026-10-28T00:00:00Z", avatar_url: null }} onChange={onChange} onLogout={onLogout} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть профиль" }));
  expect(screen.getByRole("dialog", { name: "Профиль" })).toHaveAttribute("aria-modal", "true");
  const file = new File(["photo"], "photo.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("Фотография профиля"), { target: { files: [file] } });
  await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ avatar_url: "/auth/avatar?v=1" })));
  expect(fetcher).toHaveBeenCalledWith("/auth/avatar", expect.objectContaining({ method: "PUT" }));
});
