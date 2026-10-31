import { CATEGORY_LABEL, nameFor } from '../lib/labels.js';
import { StatusGlyph } from './StatusMark.jsx';
import { STATUS_WORD } from '../lib/labels.js';

export default function Ledger({ observations, tags, selectedId, onSelect, phase }) {
  const sorted = [...observations].sort((a, b) => tags[a.id].localeCompare(tags[b.id], undefined, { numeric: true }));

  const onKey = (e, i) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const next = sorted[i + (e.key === 'ArrowDown' ? 1 : -1)];
    if (next) {
      onSelect(next.id);
      document.getElementById(`row-${next.id}`)?.focus();
    }
  };

  const counts = observations.reduce((c, o) => ({ ...c, [o.status]: (c[o.status] || 0) + 1 }), {});

  return (
    <div className="ledger">
      <div className="ledger-head">
        <h2>Parts found</h2>
        {observations.length > 0 && <span className="count">{observations.length}</span>}
      </div>

      {observations.length === 0 ? (
        <p className="empty">
          {phase === 'running' || phase === 'queued'
            ? 'Looking at the photo. Parts appear here when the model finishes.'
            : 'Parts appear here after an analysis. Each one gets a tag you can click on the photo or in this list.'}
        </p>
      ) : (
        <>
          <ul className="rows">
            {sorted.map((o, i) => (
              <li key={o.id}>
                <button
                  id={`row-${o.id}`}
                  className={`row${o.id === selectedId ? ' sel' : ''}`}
                  aria-pressed={o.id === selectedId}
                  onClick={() => onSelect(o.id)}
                  onKeyDown={(e) => onKey(e, i)}
                >
                  <span className="row-tag">{tags[o.id]}</span>
                  <span className="row-main">
                    <span className={`row-name${o.marking_text ? ' mono' : ''}`}>{nameFor(o)}</span>
                    <span className="row-sub">{CATEGORY_LABEL[o.category]}</span>
                  </span>
                  <span className={`row-status st-${o.status}`} title={STATUS_WORD[o.status]}>
                    <StatusGlyph status={o.status} />
                    <span className="sr-only">{STATUS_WORD[o.status]}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <dl className="legend">
            <div>
              <dt>
                <StatusGlyph status="confirmed" />
              </dt>
              <dd>Confirmed{counts.confirmed ? ` (${counts.confirmed})` : ''}</dd>
            </div>
            <div>
              <dt>
                <StatusGlyph status="tentative" />
              </dt>
              <dd>Tentative{counts.tentative ? ` (${counts.tentative})` : ''}</dd>
            </div>
            <div>
              <dt>
                <StatusGlyph status="unknown" />
              </dt>
              <dd>Not identified{counts.unknown ? ` (${counts.unknown})` : ''}</dd>
            </div>
          </dl>
        </>
      )}
    </div>
  );
}
