import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider, LanguageSwitch, useLanguage } from "./language";
import { DataTable } from "./features/results/DataTable";

function Sample() {
  const { t } = useLanguage();
  return <><LanguageSwitch /><p>{t("Привет", "Hello")}</p></>;
}

afterEach(() => { cleanup(); localStorage.removeItem("evia.language"); document.documentElement.lang = ""; });

it("switches language, updates the document and restores the choice", async () => {
  const view = render(<LanguageProvider><Sample /></LanguageProvider>);
  expect(screen.getByText("Привет")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("Hello")).toBeInTheDocument();
  await waitFor(() => expect(localStorage.getItem("evia.language")).toBe("en"));
  expect(document.documentElement.lang).toBe("en");
  view.unmount();
  render(<LanguageProvider><Sample /></LanguageProvider>);
  expect(screen.getByText("Hello")).toBeInTheDocument();
});

it("translates the table empty state and returns to Russian", () => {
  localStorage.setItem("evia.language", "en");
  render(<LanguageProvider><LanguageSwitch /><DataTable rows={[]} /></LanguageProvider>);
  expect(screen.getByText("No rows to display")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Русский" }));
  expect(screen.getByText("Нет строк для отображения")).toBeInTheDocument();
});
