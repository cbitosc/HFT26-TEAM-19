import { useState } from 'react';

export default function Steps({ steps, tags, onSelect, hasResult }) {
  const [done, setDone] = useState({});
  const [readings, setReadings] = useState({});

  if (!steps.length) {
    return (
      <div className="steps">
        <p className="empty">
          {hasResult
            ? 'No steps yet. Steps are written from confirmed parts and a matching reference. Confirm the board variant, or correct a part, and they will appear here.'
            : 'Steps appear after an analysis, in the order to do them, each with what you should see or measure.'}
        </p>
      </div>
    );
  }
  const finished = steps.filter((s) => done[s.id]).length;
  return (
    <div className="steps">
      <p className="progress" aria-live="polite">
        {finished} of {steps.length} done
      </p>
      <ol className="steplist">
        {steps.map((s) => (
          <li key={s.id} className={done[s.id] ? 'done' : ''}>
            <label className="check">
              <input type="checkbox" checked={!!done[s.id]} onChange={(e) => setDone({ ...done, [s.id]: e.target.checked })} />
              <span>{s.text}</span>
            </label>
            {s.expect && <p className="fine">Expect: {s.expect}</p>}
            {s.requires_measurement && (
              <label className="field inline">
                <span>Your reading{s.unit ? ` (${s.unit})` : ''}</span>
                <input inputMode="decimal" value={readings[s.id] || ''} onChange={(e) => setReadings({ ...readings, [s.id]: e.target.value })} />
              </label>
            )}
            {s.observation_ids?.length > 0 && (
              <p className="refs">
                {s.observation_ids.map((id) => (
                  <button key={id} className="chip" onClick={() => onSelect(id)}>
                    {tags[id]}
                  </button>
                ))}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
