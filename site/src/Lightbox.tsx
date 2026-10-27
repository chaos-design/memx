import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

function clamp(v: number, min: number, max: number) {
  return Math.min(max, Math.max(min, v));
}

const MIN_SCALE = 0.25;
const MAX_SCALE = 8;
/** Breathing room (px) between the fitted diagram and the viewport edges. */
const FIT_GUTTER = 24;

/**
 * Click-to-zoom lightbox for document diagrams. The diagram SVG is passed in
 * as a string and re-hosted inside a pannable/zoomable viewport.
 *
 * Sizing strategy: on open we read the SVG's `viewBox` aspect ratio and fit it
 * to the current viewport — large enough to show as much as possible while the
 * whole diagram stays visible (never upscaled past its natural size). The user
 * then zooms (wheel / buttons / pinch) and pans (drag) on top of that fit.
 */
export function Lightbox({
  svgHtml,
  title,
  onClose,
}: {
  svgHtml: string;
  title?: string;
  onClose: () => void;
}) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  // Fitted stage size (px). `null` until measured after mount.
  const [fit, setFit] = useState<{ w: number; h: number } | null>(null);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);
  const last = useRef({ x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; scale: number } | null>(null);
  const scaleRef = useRef(1);
  scaleRef.current = scale;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  // Normalise the injected SVG (strip mermaid's own width/style so CSS owns the
  // box) and compute the fit size for the current viewport. Re-fits on resize /
  // rotation so the diagram stays centred and fully visible.
  useLayoutEffect(() => {
    const svg = stageRef.current?.querySelector("svg") as SVGSVGElement | null;
    const vp = viewportRef.current;
    if (!svg || !vp) return;

    // mermaid emits width="100%" + style="max-width:<natural>px"; both fight
    // our box sizing, so hand control to CSS.
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.removeAttribute("style");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    const vb = svg.viewBox?.baseVal;
    const natW = vb && vb.width > 0 ? vb.width : 0;
    const natH = vb && vb.height > 0 ? vb.height : 0;
    const ratio = natW > 0 && natH > 0 ? natW / natH : 4 / 3;

    const compute = () => {
      const availW = Math.max(1, vp.clientWidth - FIT_GUTTER);
      const availH = Math.max(1, vp.clientHeight - FIT_GUTTER);
      let w = availW;
      let h = w / ratio;
      if (h > availH) {
        h = availH;
        w = h * ratio;
      }
      // Never upscale beyond the diagram's natural size.
      if (natW > 0 && natH > 0) {
        const cap = Math.min(1, natW / w, natH / h);
        w *= cap;
        h *= cap;
      }
      setFit({ w: Math.max(1, Math.round(w)), h: Math.max(1, Math.round(h)) });
    };

    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(vp);
    window.addEventListener("orientationchange", compute);
    return () => {
      ro.disconnect();
      window.removeEventListener("orientationchange", compute);
    };
  }, [svgHtml]);

  // Fresh diagram (or first open) starts fitted and centred.
  useEffect(() => {
    setScale(1);
    setTx(0);
    setTy(0);
  }, [svgHtml]);

  const reset = useCallback(() => {
    setScale(1);
    setTx(0);
    setTy(0);
  }, []);

  const zoomBy = useCallback((factor: number) => {
    setScale((s) => clamp(s * factor, MIN_SCALE, MAX_SCALE));
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale((s) => clamp(s * (e.deltaY < 0 ? 1.15 : 0.87), MIN_SCALE, MAX_SCALE));
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (pointers.current.size >= 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = {
        dist: Math.hypot(a.x - b.x, a.y - b.y),
        scale: scaleRef.current,
      };
      dragging.current = false;
    } else {
      dragging.current = true;
      last.current = { x: e.clientX, y: e.clientY };
    }
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

    // Two-finger pinch zooms; single-finger drag pans.
    if (pointers.current.size >= 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch.current.dist > 0) {
        setScale(clamp((pinch.current.scale * dist) / pinch.current.dist, MIN_SCALE, MAX_SCALE));
      }
      return;
    }

    if (!dragging.current) return;
    const dx = e.clientX - last.current.x;
    const dy = e.clientY - last.current.y;
    last.current = { x: e.clientX, y: e.clientY };
    setTx((x) => x + dx);
    setTy((y) => y + dy);
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    (e.target as Element).releasePointerCapture?.(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    if (pointers.current.size === 0) dragging.current = false;
  }, []);

  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={title || "图表放大"}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="lightbox-box">
        <div className="lightbox-head">
          <span className="lightbox-title">{title || "图表"}</span>
          <span className="lightbox-hint">滚轮缩放 · 拖拽平移 · 双指缩放 · Esc 关闭</span>
          <div className="lightbox-tools">
            <button
              type="button"
              className="lightbox-tool"
              onClick={() => zoomBy(1 / 1.25)}
              aria-label="缩小"
            >
              −
            </button>
            <button type="button" className="lightbox-tool" onClick={() => zoomBy(1.25)} aria-label="放大">
              +
            </button>
            <button type="button" className="lightbox-tool" onClick={reset} aria-label="适应屏幕">
              适应
            </button>
            <button
              type="button"
              className="lightbox-tool lightbox-close"
              onClick={onClose}
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        </div>
        <div
          ref={viewportRef}
          className="lightbox-viewport"
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div
            ref={stageRef}
            className="lightbox-stage"
            style={{
              width: fit ? fit.w : undefined,
              height: fit ? fit.h : undefined,
              transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
            }}
            dangerouslySetInnerHTML={{ __html: svgHtml }}
          />
        </div>
      </div>
    </div>
  );
}
