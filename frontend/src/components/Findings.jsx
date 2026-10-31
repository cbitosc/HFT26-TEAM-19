import { BOARD_VARIANTS, nameFor } from '../lib/labels.js';

function ObsLink({ id, observations, tags, onSelect }) {
  const o = observations.find((x) => x.id === id);
  if (!o) return null;
  return (
    <button className="chip" onClick={() => onSelect(id)}>
      {tags[id]}
    </button>
  );
}

export default function Findings({ observations, findings, concernsChecked, tags, onSelect, board, onBoard, hasResult }) {
  const observed = observations.filter((o) => o.status !== 'unknown');
  const unknown = observations.filter((o) => o.status === 'unknown');

  return (
    <div className="findings">
      <section>
        <h3>Board variant</h3>
        <label className="field">
          <span>Which board is this?</span>
          <select value={board || ''} onChange={(e) => e.target.value && onBoard(e.target.value)}>
            <option value="">Not confirmed</option>
            {BOARD_VARIANTS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
        <p className="fine">
          {board
            ? 'Pin diagrams appear only when the photo can be aligned to this board. Otherwise a labelled reference diagram is shown beside it.'
            : 'Pin names stay hidden until you confirm the exact board. Boards in one family can have different pinouts.'}
        </p>
      </section>

      {!hasResult ? (
        <p className="empty">Findings appear after an analysis.</p>
      ) : (
        <>
          <section>
            <h3>Seen and read</h3>
            {observed.length === 0 ? (
              <p className="muted">No part had a readable marking in this view.</p>
            ) : (
              <ul className="plain">
                {observed.map((o) => (
                  <li key={o.id}>
                    <ObsLink id={o.id} observations={observations} tags={tags} onSelect={onSelect} /> <span className={o.marking_text ? 'mono' : ''}>{nameFor(o)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3>Visual concerns to check</h3>
            {findings.length === 0 ? (
              concernsChecked ? (
                <p className="muted">No visual concern found in this view. A photo cannot show continuity, rail voltage, hidden shorts or internal damage.</p>
              ) : (
                <p className="muted">Visual concerns were not checked in this version. Look over the board yourself in bright light, and do not take this list as a sign the board is fine.</p>
              )
            ) : (
              <ul className="concerns">
                {findings.map((f) => (
                  <li key={f.id}>
                    <p className="concern-title">{f.title}</p>
                    <p>{f.detail}</p>
                    {f.verify_by && <p className="fine">Check: {f.verify_by}</p>}
                    <p className="refs">
                      {f.observation_ids?.map((id) => (
                        <ObsLink key={id} id={id} observations={observations} tags={tags} onSelect={onSelect} />
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3>Not identified</h3>
            {unknown.length === 0 ? (
              <p className="muted">Every part found has a marking.</p>
            ) : (
              <ul className="plain">
                {unknown.map((o) => (
                  <li key={o.id}>
                    <ObsLink id={o.id} observations={observations} tags={tags} onSelect={onSelect} /> {nameFor(o)}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
