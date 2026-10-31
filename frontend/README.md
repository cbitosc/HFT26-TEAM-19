# VisionGuard frontend

React + Vite. No UI kit, no CSS framework. Fonts (Schibsted Grotesk, Martian Mono) are bundled by `@fontsource-variable`,
so the app makes no network request once installed.

## Run

```powershell
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to http://127.0.0.1:8000
npm run build      # writes dist/, which the backend will serve
```

Open `http://127.0.0.1:5173/?demo=1` to review the interface with no backend and no model. Demo mode draws a synthetic
board in the browser and returns canned results. A yellow banner says so the whole time. Demo results are never
presented as an analysis of a real photo.

## Using a phone as the camera over USB

With the backend on the laptop (port 8000) and the phone connected with USB debugging on:

```powershell
adb reverse tcp:8000 tcp:8000
```

Then open `http://localhost:8000` in Chrome on the phone and choose **Use camera**. `localhost` counts as a secure
context, so the browser allows camera access without HTTPS. This route is untested on the team's hardware. If it fails,
choose **Choose photo** instead: on a phone it opens the camera app and uploads the shot.

## Layout

| Area | Role |
| --- | --- |
| Left (desktop) | Parts list. Each part has a tag (U1, C2, J1...) that matches its box on the photo. |
| Centre | The photo with boxes. Drag to pan, wheel or pinch to zoom, arrow keys when focused. |
| Right | Part detail, Findings, Steps. A gold trace joins the selected box to its detail. |
| Phone | Photo on top; tabs for Parts, Part, Findings, Steps below. |

Tags are VisionGuard's own numbering. They are not text read from the board, and the UI says so.
Status is shown by glyph, word and line style together: confirmed is a solid box, tentative is dashed,
not identified is dotted. Colour is never the only signal.

## Source map

- `src/lib/api.js` the only place that talks to the backend (`docs/api-contract.md`)
- `src/lib/demo.js` synthetic board and canned results
- `src/lib/geometry.js`, `labels.js` pure helpers
- `src/components/Canvas.jsx` photo, pan/zoom, SVG overlay, box drawing
- `src/components/Trace.jsx` the routed trace
- `src/styles.css` all styling, tokens at the top

## Not yet verified

- Against a real model. The browser has been run against the real API with the MOCK adapter only.
- With real photos of real boards, including EXIF-rotated phone photos.
- Camera capture on a real device, and the `adb reverse` route.
- Screen readers and keyboard-only use beyond a basic pass.
