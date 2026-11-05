import { render, screen, within } from "@testing-library/react";
import { HomePage } from "./HomePage";

it("keeps recent conversations in a dedicated side region", () => {
  render(<HomePage
    sources={[]}
    selectedSourceId={null}
    chats={[
      { chat_id: "chat-1", title: "Продажи по месяцам", source_id: "source-1", created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z" },
    ]}
    chatLoading={false}
    chatError=""
    loading={false}
    error=""
    uploadCard={<div>CSV</div>}
    onRefresh={() => {}}
    onSelectSource={() => {}}
    onPostgres={() => {}}
    onReports={() => {}}
    onOpenChat={() => {}}
    onRefreshChats={() => {}}
  />);

  const history = screen.getByRole("complementary", { name: "Недавние диалоги" });
  expect(within(history).getByRole("button", { name: /Продажи по месяцам/ })).toBeInTheDocument();
  expect(history.querySelector(".home-recent-scroll")).toBeInTheDocument();
});
