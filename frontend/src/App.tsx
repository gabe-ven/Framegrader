import { lazy, Suspense } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router";
import { PhotoSkeleton } from "@/components/Shimmer";
import { MessagePage } from "@/features/analysis/MessagePage";
import { UploadPanel } from "@/features/upload/UploadPanel";

// Everything past the landing page is split out: the report pulls in d3,
// recharts, nivo and three; the editor pulls in echarts. None of it is needed
// to paint the hero, which is the only thing a first-time visitor sees.
const ResultPage = lazy(() =>
  import("@/features/analysis/ResultPage").then((m) => ({ default: m.ResultPage })),
);
const EditRoute = lazy(() =>
  import("@/features/analysis/EditRoute").then((m) => ({ default: m.EditRoute })),
);
const HistoryPage = lazy(() =>
  import("@/features/history/HistoryPage").then((m) => ({ default: m.HistoryPage })),
);

/**
 * Real URLs for every screen, so back/forward, refresh, and links all work:
 *
 *   /             pick and preview a photo
 *   /r/:id        progress, then the report (also the public share link)
 *   /r/:id/edit   the editor
 *   /history      this browser's past analyses
 */
export default function App() {
  return (
    <main className="min-h-screen bg-page text-ink">
      <SiteNav />
      <div className="mx-auto max-w-5xl px-6">
        <Suspense
          fallback={
            <div className="flex min-h-screen items-center justify-center">
              <PhotoSkeleton />
            </div>
          }
        >
        <Routes>
          <Route path="/" element={<UploadPanel />} />
          <Route path="/r/:id" element={<ResultPage />} />
          <Route path="/r/:id/edit" element={<EditRoute />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route
            path="*"
            element={<MessagePage title="Page not found" body="There's nothing at this address." />}
          />
        </Routes>
        </Suspense>
      </div>
    </main>
  );
}

// pointer-coarse: a 44px-tall target on touch screens; the compact pill stays
// for mouse users.
const NAV_LINK =
  "border-4 border-black bg-white px-3 py-1.5 font-mono text-[11px] font-black uppercase " +
  "tracking-widest text-black shadow-[3px_3px_0_0_#000] hover:bg-yellow-400 " +
  "pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center";

/** Small fixed corner nav; hidden on the landing page, which has its own CTA. */
function SiteNav() {
  const { pathname } = useLocation();
  // Below lg the editor pins the photo to the top of the screen, and the nav
  // would sit on top of its compare buttons. The editor has its own Back.
  const hideOnSmall = pathname.endsWith("/edit") ? "max-lg:hidden" : "";
  if (pathname === "/") {
    return (
      <nav className="fixed right-4 top-4 z-50">
        <NavLink to="/history" className={NAV_LINK}>
          History
        </NavLink>
      </nav>
    );
  }
  return (
    <nav className={`fixed right-4 top-4 z-50 flex gap-2 ${hideOnSmall}`}>
      <NavLink to="/" className={NAV_LINK}>
        New photo
      </NavLink>
      {pathname !== "/history" && (
        <NavLink to="/history" className={NAV_LINK}>
          History
        </NavLink>
      )}
    </nav>
  );
}
