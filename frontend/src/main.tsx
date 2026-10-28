import { StrictMode, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
const AuthGate = lazy(() => import("./AuthGate"));
const MascotGallery = lazy(() => import("./features/mascot/MascotGallery"));
const gallery =
  new URLSearchParams(window.location.search).get("mascot") === "1";
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Suspense
      fallback={
        <p role="status">
          {gallery
            ? "Загружаем галерею EVIA…"
            : "Загружаем рабочее пространство…"}
        </p>
      }
    >
      {gallery ? <MascotGallery /> : <AuthGate />}
    </Suspense>
  </StrictMode>,
);
