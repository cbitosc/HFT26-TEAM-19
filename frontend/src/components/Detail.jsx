import { useEffect, useState } from 'react';
import { cropViewBox } from '../lib/geometry.js';
import { CATEGORIES, CATEGORY_LABEL, nameFor } from '../lib/labels.js';
import StatusMark from './StatusMark.jsx';

function Crop({ image, bbox, status }) {
  const vb = cropViewBox(bbox, image.width, image.height);
  return (
    <svg className="crop" viewBox={vb.join(' ')} role="img" aria-label="Close-up of the selected part from the photo" preserveAspectRatio="xMidYMid slice">
      <rect x={vb[0]} y={vb[1]} width={vb[2]} height={vb[3]} fill="#0a1512" />
      <image href={image.url} x="0" y="0" width={image.width} height={image.height} />
      <rect
        className={`crop-box st-${status}`}
        x={bbox[0]}
        y={bbox[1]}
        width={bbox[2] - bbox[0]}
        height={bbox[3] - bbox[1]}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function Correct({ o, onSave, onRedraw, saving }) {
  const [category, setCategory] = useState(o.category);
  const [marking, setMarking] = useState(o.marking_text || '');
  const [identity, setIdentity] = useState(o.candidates?.[0]?.identity || '');
  const [confirm, setConfirm] = useState(o.status === 'confirmed');

  useEffect(() => {
    setCategory(o.category);
    setMarking(o.marking_text || '');
    setIdentity(o.candidates?.[0]?.identity || '');
    setConfirm(o.status === 'confirmed');
  }, [o.id, o.category, o.marking_text, o.status, o.candidates]);

  return (
    <form
      className="correct"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({ category, marking_text: marking.trim(), identity: identity.trim(), confirmed: confirm });
      }}
    >
      <label className="field">
        <span>Part type</span>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Marking printed on the part</span>
        <input className="mono" value={marking} onChange={(e) => setMarking(e.target.value)} spellCheck={false} autoCapitalize="characters" />
      </label>
      <label className="field">
        <span>Part you think it is</span>
        <input value={identity} onChange={(e) => setIdentity(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
        <span>I checked this against the physical part</span>
      </label>
      <div className="actions">
        <button type="submit" className="btn primary" disabled={saving}>
          Save changes
        </button>
        <button type="button" className="btn" onClick={onRedraw}>
          Redraw box
        </button>
      </div>
      <p className="fine">Saving a change clears findings and steps that depended on this part, then rebuilds them.</p>
    </form>
  );
}

export default function Detail({ image, o, tag, onCorrect, onRedraw, onSimilar, similarNote, saving }) {
  if (!o) {
    return (
      <div className="detail empty-detail" id="trace-anchor">
        <h2>No part selected</h2>
        <p className="empty">Click a box on the photo or a row in the parts list to see what was read, the evidence, and any references.</p>
      </div>
    );
  }
  const hasRefs = o.reference_ids?.length > 0;
  return (
    <div className="detail">
      <header className="detail-head" id="trace-anchor">
        <span className="tagbig">{tag}</span>
        <div>
          <h2 className={o.marking_text ? 'mono' : ''}>{nameFor(o)}</h2>
          <p className="sub">
            {CATEGORY_LABEL[o.category]}
            {o.source === 'user' ? ', edited by you' : ''}
            {o.source === 'assist' ? ', found by appearance' : ''}
          </p>
        </div>
      </header>

      <Crop image={image} bbox={o.bbox} status={o.status} />

      <section>
        <h3>Status</h3>
        <StatusMark status={o.status} />
        <p className="fine">
          {o.status === 'unknown' && o.source === 'assist' && 'This looks like another part on the board. Nobody has read it. Redraw or correct it if the box is off.'}
          {o.status === 'unknown' && o.source !== 'assist' && 'The part type is visible but the model could not read a marking to identify it.'}
          {o.status === 'tentative' && 'The model read a marking. Only a matching reference or your confirmation makes it confirmed.'}
          {o.status === 'confirmed' && (o.source === 'user' ? 'You confirmed this against the part.' : 'Matched a reference exactly.')}
        </p>
      </section>

      <section>
        <h3>Printed marking</h3>
        {o.marking_text ? <p className="mono big">{o.marking_text}</p> : <p className="muted">No readable marking in this view.</p>}
        {o.candidates?.length > 0 && (
          <p className="fine">
            Model guess: {o.candidates.map((c) => c.identity).join(', ')}. Not checked against a datasheet.
          </p>
        )}
      </section>

      {o.evidence?.length > 0 && (
        <section>
          <h3>Evidence</h3>
          <ul className="plain">
            {o.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </section>
      )}

      {o.limitations?.length > 0 && (
        <section>
          <h3>What this view cannot show</h3>
          <ul className="plain">
            {o.limitations.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>References</h3>
        {hasRefs ? (
          <ul className="plain">
            {o.reference_ids.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">Verification unavailable. No matching reference is in the local library, so no pin or voltage facts are shown for this part.</p>
        )}
        {o.model_score != null && <p className="fine">Model score {o.model_score.toFixed(2)}. This is an uncalibrated estimate, not a probability.</p>}
      </section>

      {onSimilar && o.category !== 'board' && (
        <section>
          <h3>Repeated parts</h3>
          <button type="button" className="btn" onClick={onSimilar} disabled={saving}>
            {saving ? 'Searching…' : 'Find more like this'}
          </button>
          <p className="fine">Searches the whole photo for parts that look like this box. Works best when the box fits the part tightly.</p>
          {similarNote && <p className="fine" role="status">{similarNote}</p>}
        </section>
      )}

      <details className="fix">
        <summary>Correct this part</summary>
        <Correct o={o} onSave={(p) => onCorrect(o.id, p)} onRedraw={onRedraw} saving={saving} />
      </details>

      <p className="fine tagnote">The tag {tag} is VisionGuard&rsquo;s own numbering. It is not text read from the board.</p>
    </div>
  );
}
