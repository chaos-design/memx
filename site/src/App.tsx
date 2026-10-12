import { useEffect, useRef, type ReactNode } from "react";
import { BottomBar } from "./BottomBar";
import { ArtifactView } from "./ArtifactView";
import { DocView } from "./DocView";
import { Gallery } from "./Gallery";
import { Home } from "./Home";
import { LangProvider } from "./i18n";
import { useHashRoute } from "./routes";
import { Sidebar } from "./Sidebar";

function Shell() {
  const route = useHashRoute();
  const contentRef = useRef<HTMLElement | null>(null);
  // The content column owns the scroll position now, so a route change must
  // reset it explicitly — otherwise the next page opens mid-document.
  const routeKey = `${route.kind}:${"slug" in route ? route.slug : ""}`;

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [routeKey]);

  let view: ReactNode;
  switch (route.kind) {
    case "home":
      view = <Home />;
      break;
    case "doc":
      view = <DocView key={route.slug} slug={route.slug} />;
      break;
    case "artifact":
      view = <ArtifactView key={route.slug} slug={route.slug} />;
      break;
    case "gallery":
      view = <Gallery />;
      break;
    default:
      view = <Home />;
  }

  return (
    <div className="shell">
      <Sidebar route={route} />
      <main className="content" ref={contentRef}>
        {view}
      </main>
      <BottomBar />
    </div>
  );
}

export function App() {
  return (
    <LangProvider>
      <Shell />
    </LangProvider>
  );
}
