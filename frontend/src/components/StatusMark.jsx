import { STATUS_WORD } from '../lib/labels.js';

// Status is carried by glyph shape and a word, never colour alone.
export function StatusGlyph({ status, size = 12 }) {
  return (
    <svg className={`glyph glyph-${status}`} width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
      {status === 'confirmed' && <rect x="1" y="1" width="10" height="10" fill="currentColor" />}
      {status === 'tentative' && <polygon points="1,1 11,11 1,11" fill="currentColor" />}
    </svg>
  );
}

export default function StatusMark({ status }) {
  return (
    <span className={`status status-${status}`}>
      <StatusGlyph status={status} />
      <span>{STATUS_WORD[status] ?? status}</span>
    </span>
  );
}
