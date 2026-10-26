import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArtifactView } from "./ArtifactView";
import { DocView } from "./DocView";
import { Gallery } from "./Gallery";
import { Header } from "./Header";
import { Home } from "./Home";
import { LangProvider } from "./i18n";
import { useHashRoute } from "./routes";
import { Sidebar } from "./Sidebar";

/** Must stay in sync with the mobile breakpoint in styles.css (860px). */
const MOBILE_NAV_QUERY = "(max-width: 860px)";

function Shell() {
  const route = useHashRoute();
  const contentRef = useRef<HTMLElement | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const [navOpen, setNavOpen] = useState(false);
  // The content column owns the scroll position now, so a route change must
  // reset it explicitly — otherwise the next page opens mid-document.
  const routeKey = `${route.kind}:${"slug" in route ? route.slug : ""}`;

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [routeKey]);

  const closeNav = useCallback((restoreFocus = false) => {
    setNavOpen(false);
    if (restoreFocus) toggleRef.current?.focus();
  }, []);

  // Any navigation closes the mobile panel; focus stays on the link the user
  // just activated rather than jumping back to the toggle.
  useEffect(() => {
    setNavOpen(false);
  }, [routeKey]);

  // Esc closes the panel and hands focus back to the toggle.
  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeNav(true);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen, closeNav]);

  // Rotating to a desktop-width viewport must never leave the mobile panel open.
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_NAV_QUERY);
    const onChange = () => {
      if (!mq.matches) setNavOpen(false);
    };
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Freeze the page behind the panel so the dropdown scrolls on its own.
  useEffect(() => {
    if (!navOpen) return;
    document.body.classList.add("nav-open");
    return () => document.body.classList.remove("nav-open");
  }, [navOpen]);

  // Opening moves the focus ring into the panel, so Tab walks its items next.
  useEffect(() => {
    if (navOpen) navRef.current?.focus();
  }, [navOpen]);

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
    <div className="shell" data-nav-open={navOpen ? "true" : "false"}>
      <Header open={navOpen} onToggle={() => setNavOpen((v) => !v)} toggleRef={toggleRef} />
      <Sidebar ref={navRef} route={route} />
      {navOpen ? (
        <div className="nav-backdrop" onClick={() => closeNav(true)} aria-hidden="true" />
      ) : null}
      <main className="content" ref={contentRef}>
        {view}
      </main>
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
