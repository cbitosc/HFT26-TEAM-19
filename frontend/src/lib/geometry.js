// Mirror of backend/app/geometry.py display maths. Boxes arrive in ORIGINAL pixels; the
// overlay SVG uses the original size as its viewBox, so only pan/zoom is applied here.

export const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

export function fitScale(containerW, containerH, imgW, imgH, margin = 32) {
  if (!containerW || !containerH || !imgW || !imgH) return 1;
  return Math.max(0.01, Math.min((containerW - margin * 2) / imgW, (containerH - margin * 2) / imgH));
}

export function centerView(containerW, containerH, imgW, imgH, k) {
  return { k, x: (containerW - imgW * k) / 2, y: (containerH - imgH * k) / 2 };
}

export function screenToImage(clientX, clientY, containerRect, view) {
  return { x: (clientX - containerRect.left - view.x) / view.k, y: (clientY - containerRect.top - view.y) / view.k };
}

export function boxArea(b) {
  return Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
}

/** viewBox that crops the image to a padded box at a fixed aspect ratio. */
export function cropViewBox(bbox, imgW, imgH, aspect = 1.7, pad = 0.35) {
  let w = Math.max(60, (bbox[2] - bbox[0]) * (1 + pad * 2));
  let h = Math.max(60, (bbox[3] - bbox[1]) * (1 + pad * 2));
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  const cx = (bbox[0] + bbox[2]) / 2;
  const cy = (bbox[1] + bbox[3]) / 2;
  let x = cx - w / 2;
  let y = cy - h / 2;
  if (w <= imgW) x = clamp(x, 0, imgW - w);
  if (h <= imgH) y = clamp(y, 0, imgH - h);
  return [x, y, w, h];
}

export function normalizeBox(a, b, maxW, maxH) {
  const x1 = clamp(Math.min(a.x, b.x), 0, maxW);
  const y1 = clamp(Math.min(a.y, b.y), 0, maxH);
  const x2 = clamp(Math.max(a.x, b.x), 0, maxW);
  const y2 = clamp(Math.max(a.y, b.y), 0, maxH);
  return [x1, y1, x2, y2];
}
