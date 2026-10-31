import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { boxArea, centerView, clamp, fitScale, normalizeBox, screenToImage } from '../lib/geometry.js';
import { CATEGORY_LABEL, nameFor } from '../lib/labels.js';

const MIN_DRAW = 8; // original px

export default function Canvas({
  image,
  observations,
  tags,
  selectedId,
  onSelect,
  drawFor,
  onDraw,
  onCancelDraw,
  analysisKey,
  onMismatch,
}) {
  const stage = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const [moved, setMoved] = useState(false);
  const [draft, setDraft] = useState(null);
  const viewRef = useRef(view);
  viewRef.current = view;
  const pointers = useRef(new Map());
  const gesture = useRef(null);
  const dragged = useRef(false);

  const fit = useMemo(() => fitScale(size.w, size.h, image.width, image.height), [size, image.width, image.height]);

  useLayoutEffect(() => {
    const el = stage.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Fit to window until the person moves the view.
  useEffect(() => {
    if (!moved && size.w && image.width) setView(centerView(size.w, size.h, image.width, image.height, fit));
  }, [moved, size.w, size.h, image.width, image.height, fit]);

  useEffect(() => {
    setMoved(false);
  }, [image.url]);

  const zoomAt = useCallback(
    (factor, cx, cy) => {
      setMoved(true);
      setView((v) => {
        const k = clamp(v.k * factor, fit * 0.5, Math.max(fit * 16, 4));
        const r = k / v.k;
        return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
      });
    },
    [fit],
  );

  const zoomCenter = (factor) => zoomAt(factor, size.w / 2, size.h / 2);
  const resetFit = () => setMoved(false);
  const actualSize = () => {
    setMoved(true);
    setView(centerView(size.w, size.h, image.width, image.height, 1));
  };

  // Non-passive wheel so the page does not scroll while zooming.
  useEffect(() => {
    const el = stage.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018)), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  // Pointer handling: one pointer pans (or draws), two pointers pinch.
  useEffect(() => {
    const move = (e) => {
      if (!pointers.current.has(e.pointerId)) return;
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const el = stage.current;
      const rect = el.getBoundingClientRect();
      const g = gesture.current;
      if (!g) return;
      if (pointers.current.size >= 2 && g.type !== 'draw') {
        const [a, b] = [...pointers.current.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        const mid = { x: (a.x + b.x) / 2 - rect.left, y: (a.y + b.y) / 2 - rect.top };
        if (g.type !== 'pinch') {
          gesture.current = { type: 'pinch', dist, mid };
          return;
        }
        dragged.current = true;
        zoomAt(dist / g.dist, mid.x, mid.y);
        setView((v) => ({ ...v, x: v.x + (mid.x - g.mid.x), y: v.y + (mid.y - g.mid.y) }));
        gesture.current = { type: 'pinch', dist, mid };
        return;
      }
      const dx = e.clientX - g.sx;
      const dy = e.clientY - g.sy;
      if (Math.hypot(dx, dy) > 4) dragged.current = true;
      if (g.type === 'pan') {
        setMoved(true);
        setView({ k: g.view.k, x: g.view.x + dx, y: g.view.y + dy });
      } else if (g.type === 'draw') {
        setDraft(normalizeBox(g.start, screenToImage(e.clientX, e.clientY, rect, viewRef.current), image.width, image.height));
      }
    };
    const up = (e) => {
      if (!pointers.current.has(e.pointerId)) return;
      pointers.current.delete(e.pointerId);
      const g = gesture.current;
      if (g?.type === 'draw' && pointers.current.size === 0) {
        const box = normalizeBox(g.start, screenToImage(e.clientX, e.clientY, stage.current.getBoundingClientRect(), viewRef.current), image.width, image.height);
        setDraft(null);
        if (box[2] - box[0] >= MIN_DRAW && box[3] - box[1] >= MIN_DRAW) onDraw?.(box);
      }
      if (pointers.current.size === 0) {
        gesture.current = null;
        setTimeout(() => {
          dragged.current = false;
        }, 0);
      } else if (pointers.current.size === 1) {
        const p = [...pointers.current.values()][0];
        gesture.current = { type: 'pan', sx: p.x, sy: p.y, view: viewRef.current };
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [zoomAt, onDraw, image.width, image.height]);

  const onPointerDown = (e) => {
    if (e.button && e.button !== 0) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    dragged.current = false;
    const rect = stage.current.getBoundingClientRect();
    if (pointers.current.size === 1) {
      if (drawFor) {
        const start = screenToImage(e.clientX, e.clientY, rect, viewRef.current);
        gesture.current = { type: 'draw', start };
        setDraft([start.x, start.y, start.x, start.y]);
      } else {
        gesture.current = { type: 'pan', sx: e.clientX, sy: e.clientY, view: viewRef.current };
      }
    }
  };

  const onKeyDown = (e) => {
    if (e.target !== stage.current) return;
    const step = 60;
    const keys = {
      '+': () => zoomCenter(1.25),
      '=': () => zoomCenter(1.25),
      '-': () => zoomCenter(0.8),
      '0': resetFit,
      ArrowLeft: () => pan(step, 0),
      ArrowRight: () => pan(-step, 0),
      ArrowUp: () => pan(0, step),
      ArrowDown: () => pan(0, -step),
      Escape: () => onCancelDraw?.(),
    };
    if (keys[e.key]) {
      e.preventDefault();
      keys[e.key]();
    }
  };
  const pan = (dx, dy) => {
    setMoved(true);
    setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  };

  const onImgLoad = (e) => {
    const { naturalWidth: nw, naturalHeight: nh } = e.target;
    if (image.width && Math.abs(nw / nh - image.width / image.height) > 0.01 * (image.width / image.height)) {
      onMismatch?.(`The photo shows as ${nw}x${nh} here but the server read it as ${image.width}x${image.height}. Boxes would be misplaced, so analysis is blocked. Re-save the photo without rotation metadata and try again.`);
    }
  };

  const ordered = useMemo(() => [...observations].sort((a, b) => boxArea(b.bbox) - boxArea(a.bbox)), [observations]);
  const k = view.k;
  const tagPx = 12 / k;

  return (
    <div
      id="stage"
      ref={stage}
      className={`stage${drawFor ? ' drawing' : ''}`}
      tabIndex={0}
      role="application"
      aria-label="Photo viewer. Plus and minus zoom, arrow keys pan, zero fits the photo."
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      <div className="plane" style={{ width: image.width, height: image.height, transform: `translate(${view.x}px, ${view.y}px) scale(${k})` }}>
        <img src={image.url} width={image.width} height={image.height} alt="Photo of the board under inspection" draggable={false} onLoad={onImgLoad} />
        <svg className="overlay" viewBox={`0 0 ${image.width} ${image.height}`} width={image.width} height={image.height}>
          <g key={analysisKey}>
            {ordered.map((o, i) => {
              const [x1, y1, x2, y2] = o.bbox;
              const sel = o.id === selectedId;
              const tag = tags[o.id];
              const tw = (tag.length * 8.2 + 10) / k;
              const th = 18 / k;
              return (
                <g
                  key={o.id}
                  data-obs={o.id}
                  className={`box st-${o.status}${sel ? ' sel' : ''}`}
                  style={{ animationDelay: `${i * 45}ms` }}
                  role="button"
                  tabIndex={0}
                  aria-pressed={sel}
                  aria-label={`${tag}, ${CATEGORY_LABEL[o.category]}, ${nameFor(o)}, ${o.status === 'unknown' ? 'not identified' : o.status}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!dragged.current && !drawFor) onSelect(o.id);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onSelect(o.id);
                    }
                  }}
                >
                  <rect className="box-halo" x={x1} y={y1} width={x2 - x1} height={y2 - y1} />
                  <rect className="box-main" x={x1} y={y1} width={x2 - x1} height={y2 - y1} />
                  <rect className="tag-bg" x={x1} y={y1 - th} width={tw} height={th} />
                  <text className="tag-text" x={x1 + 5 / k} y={y1 - th / 2 + tagPx * 0.36} fontSize={tagPx}>
                    {tag}
                  </text>
                </g>
              );
            })}
          </g>
          {draft && (
            <rect className="draft" x={draft[0]} y={draft[1]} width={draft[2] - draft[0]} height={draft[3] - draft[1]} />
          )}
        </svg>
      </div>

      {drawFor && (
        <div className="draw-hint" role="status">
          Drag on the photo to draw the new box. <button className="linklike" onClick={onCancelDraw}>Cancel</button>
        </div>
      )}

      <div className="zoombar" role="toolbar" aria-label="Zoom">
        <button className="btn sq" onClick={() => zoomCenter(0.8)} aria-label="Zoom out">
          −
        </button>
        <span className="zoomval" aria-live="polite">
          {Math.round((k / 1) * 100)}%
        </span>
        <button className="btn sq" onClick={() => zoomCenter(1.25)} aria-label="Zoom in">
          +
        </button>
        <button className="btn" onClick={resetFit}>
          Fit
        </button>
        <button className="btn" onClick={actualSize}>
          1:1
        </button>
      </div>
    </div>
  );
}
