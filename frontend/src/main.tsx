import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { LanguageProvider, useLanguage } from "./language";
import "./styles.css";
const AuthGate = lazy(() => import("./AuthGate"));
const MascotGallery = lazy(() => import("./features/mascot/MascotGallery"));
const gallery =
  new URLSearchParams(window.location.search).get("mascot") === "1";
function Loading() {
  const { t } = useLanguage();
  return <p role="status">{gallery ? t("Загружаем галерею EVIA…", "Loading EVIA gallery…") : t("Загружаем рабочее пространство…", "Loading workspace…")}</p>;
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LanguageProvider>
    <Suspense fallback={<Loading />}>
      {gallery ? <MascotGallery /> : <AuthGate />}
    </Suspense>
    </LanguageProvider>
  </StrictMode>,
);
