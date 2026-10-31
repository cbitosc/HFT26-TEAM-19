import { useEffect, useRef } from 'react';

// A routed trace (horizontal run, 45 degree jog, horizontal run) from the selected box on the
// photo to the detail panel it belongs to. It encodes which part the panel is describing.
export default function Trace({ selectedId, enabled }) {
  const svg = useRef(null);
  const halo = useRef(null);
  const line = useRef(null);
  const via1 = useRef(null);
  const via2 = useRef(null);

  useEffect(() => {
    if (!enabled || !selectedId) return undefined;
    let raf = 0;
    const tick = () => {
      const box = document.querySelector(`[data-obs="${CSS.escape(selectedId)}"] .box-main`);
      const anchor = document.getElementById('trace-anchor');
      const stage = document.getElementById('stage');
      const el = svg.current;
      if (el && box && anchor && stage) {
        const b = box.getBoundingClientRect();
        const s = stage.getBoundingClientRect();
        const a = anchor.getBoundingClientRect();
        const visible = b.right > s.left && b.left < s.right && b.bottom > s.top && b.top < s.bottom && a.width > 0;
        el.style.visibility = visible ? 'visible' : 'hidden';
        if (visible) {
          const sx = Math.min(b.right, s.right - 6);
          const sy = Math.min(Math.max(b.top + b.height / 2, s.top + 6), s.bottom - 6);
          const ex = a.left;
          // When the detail panel is scrolled, end the trace at the panel's edge instead of off-screen.
          const body = document.querySelector('.inspector-body')?.getBoundingClientRect();
          const rawEy = a.top + 20;
          const ey = body && body.height > 0 && window.innerWidth >= 1000 ? Math.min(Math.max(rawEy, body.top + 6), body.bottom - 6) : rawEy;
          const jog = Math.abs(ey - sy);
          const x2 = ex - 16;
          const x1 = x2 - jog;
          let d;
          if (x1 > sx + 8) {
            d = `M${sx} ${sy}H${x1}L${x2} ${ey}H${ex}`;
          } else if (x2 > sx + 8) {
            // Not enough room for the jog: run 45 degrees as far as there is room, then straight down or up.
            const run = Math.min(x2 - sx, jog);
            const sign = ey >= sy ? 1 : -1;
            d = `M${sx} ${sy}L${sx + run} ${sy + sign * run}V${ey}H${ex}`;
          } else {
            d = `M${sx} ${sy}H${ex}V${ey}`;
          }
          halo.current?.setAttribute('d', d);
          line.current?.setAttribute('d', d);
          via1.current?.setAttribute('cx', sx);
          via1.current?.setAttribute('cy', sy);
          via2.current?.setAttribute('cx', ex);
          via2.current?.setAttribute('cy', ey);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [enabled, selectedId]);

  if (!enabled || !selectedId) return null;
  return (
    <svg ref={svg} className="trace" aria-hidden="true" focusable="false">
      <path ref={halo} className="trace-halo" fill="none" />
      <path key={selectedId} ref={line} className="trace-line" fill="none" pathLength="1" />
      <circle ref={via1} className="via" r="4" />
      <circle ref={via2} className="via ring" r="5" />
    </svg>
  );
}
