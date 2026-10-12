/** Loading affordances: a spinner row and a document skeleton placeholder. */

export function Loading({ label, large = false }: { label: string; large?: boolean }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className={large ? "spinner lg" : "spinner"} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/**
 * Skeleton shown while a doc is being rendered (markdown parse + mermaid pass).
 * Mirrors the rough shape of a document so the layout does not jump once the
 * real content arrives.
 */
export function DocSkeleton({ label }: { label: string }) {
  return (
    <div className="doc-skeleton" role="status" aria-live="polite" aria-busy="true">
      <Loading label={label} />
      <div className="sk-line sk-title" />
      <div className="sk-line" style={{ width: "92%" }} />
      <div className="sk-line" style={{ width: "78%" }} />
      <div className="sk-line" style={{ width: "85%" }} />
      <div className="sk-line sk-block" style={{ width: "64%" }} />
      <div className="sk-line" style={{ width: "88%" }} />
      <div className="sk-line" style={{ width: "52%" }} />
    </div>
  );
}

/** Overlay spinner for an embedded iframe that has not fired `load` yet. */
export function FrameLoading({ label }: { label: string }) {
  return (
    <div className="frame-loading" role="status" aria-live="polite">
      <Loading label={label} large />
    </div>
  );
}
