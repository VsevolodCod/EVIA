import { renderHook, act } from "@testing-library/react";
import { LanguageProvider, useLanguage } from "./i18n";

function wrapper({ children }: { children: React.ReactNode }) {
  return <LanguageProvider>{children}</LanguageProvider>;
}

it("defaults to Russian and restores the saved language", () => {
  localStorage.removeItem("evia.language");
  const russian = renderHook(() => useLanguage(), { wrapper });
  expect(russian.result.current.locale).toBe("ru");
  russian.unmount();

  localStorage.setItem("evia.language", "en");
  const english = renderHook(() => useLanguage(), { wrapper });
  expect(english.result.current.locale).toBe("en");
  expect(english.result.current.t("Настройки")).toBe("Settings");
});

it("updates the active locale and persists the selection", () => {
  localStorage.removeItem("evia.language");
  const { result } = renderHook(() => useLanguage(), { wrapper });
  act(() => result.current.setLocale("en"));
  expect(result.current.locale).toBe("en");
  expect(localStorage.getItem("evia.language")).toBe("en");
  expect(result.current.t("Главная")).toBe("Home");
});
