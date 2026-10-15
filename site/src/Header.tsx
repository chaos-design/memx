import type { RefObject } from "react";
import { nextLang, useLang } from "./i18n";
import { ROUTES } from "./routes";

/**
 * Mobile-only top bar. Desktop keeps the pinned sidebar, so this bar is hidden
 * there (see the `max-width: 860px` block in styles.css). On mobile it carries
 * the brand, the language pill (moved up from the sidebar footer) and the
 * toggle that expands the shared sidebar as a dropdown panel.
 */
export function Header({
  open,
  onToggle,
  toggleRef,
}: {
  open: boolean;
  onToggle: () => void;
  toggleRef: RefObject<HTMLButtonElement | null>;
}) {
  const { lang, setLang, t } = useLang();

  return (
    <header className="site-header">
      <a className="site-header-brand" href={ROUTES.home}>
        <span className="brand-mark">M</span>
        <span className="site-header-text">
          <span className="brand-name">memx</span>
          <span className="brand-sub">{t.brandSub}</span>
        </span>
      </a>

      <div className="site-header-actions">
        <button
          type="button"
          className="lang-toggle"
          onClick={() => setLang(nextLang(lang))}
          title={t.langTitle}
          aria-label={t.langTitle}
        >
          {t.langLabel}
        </button>
        <button
          type="button"
          ref={toggleRef}
          className={`nav-toggle${open ? " open" : ""}`}
          onClick={onToggle}
          aria-expanded={open}
          aria-controls="site-nav"
          aria-label={open ? t.navClose : t.navOpen}
        >
          <span className="nav-toggle-bars" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </button>
      </div>
    </header>
  );
}
