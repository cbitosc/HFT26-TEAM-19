import { useRef, useState } from 'react';

function Fiducial({ className }) {
  // Real PCBs carry these alignment targets; here they mark where the photo goes.
  return (
    <svg className={`fid ${className}`} width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
      <circle cx="13" cy="13" r="5" fill="currentColor" />
      <circle cx="13" cy="13" r="11" fill="none" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export default function Intake({ onFile, onCamera, onDemo, demo, error, busy }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);

  const pick = (files) => {
    const f = files && files[0];
    if (f) onFile(f);
  };

  return (
    <div
      className={`intake${over ? ' over' : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        pick(e.dataTransfer.files);
      }}
    >
      <Fiducial className="tl" />
      <Fiducial className="tr" />
      <Fiducial className="bl" />
      <Fiducial className="br" />

      <div className="intake-body">
        <h1>Drop a photo of the board</h1>
        <p className="lede">
          VisionGuard marks the parts it can see and says what it could not read. It never treats a photo as proof
          that a board is safe to power.
        </p>

        <ul className="tips">
          <li>Use even light with no glare on the chips.</li>
          <li>Hold the camera steady and fill the frame with the board.</li>
          <li>For a printed marking, take a second close-up from directly above it.</li>
        </ul>

        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}

        <div className="actions">
          <button className="btn primary" onClick={() => input.current?.click()} disabled={busy || demo}>
            Choose photo
          </button>
          <button className="btn" onClick={onCamera} disabled={busy || demo}>
            Use camera
          </button>
          {demo && (
            <button className="btn primary" onClick={onDemo} disabled={busy}>
              Load demo board
            </button>
          )}
        </div>
        {demo && (
          <p className="fine">
            Demo mode draws a synthetic board with canned results. Start the backend and open the app without
            <code> ?demo </code> to inspect real photos.
          </p>
        )}
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          hidden
          onChange={(e) => {
            pick(e.target.files);
            e.target.value = '';
          }}
        />
      </div>
    </div>
  );
}
