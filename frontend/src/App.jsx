import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, isDemo } from './lib/api.js';
import { assignTags } from './lib/labels.js';
import Camera from './components/Camera.jsx';
import Canvas from './components/Canvas.jsx';
import Detail from './components/Detail.jsx';
import Findings from './components/Findings.jsx';
import Intake from './components/Intake.jsx';
import Ledger from './components/Ledger.jsx';
import Steps from './components/Steps.jsx';
import Trace from './components/Trace.jsx';

const BUSY = ['uploading', 'queued', 'running'];

function useMedia(query) {
  const [m, setM] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setM(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [query]);
  return m;
}

function Mark() {
  return (
    <svg className="mark" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="3.6" fill="currentColor" />
      <circle cx="11" cy="11" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M11 0.5v4M11 17.5v4M0.5 11h4M17.5 11h4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export default function App() {
  const [image, setImage] = useState(null);
  const [a, setA] = useState({ phase: 'idle' });
  const [obs, setObs] = useState([]);
  const [extra, setExtra] = useState({ findings: [], steps: [], concernsChecked: false });
  const [meta, setMeta] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState('part');
  const [partsOnPhone, setPartsOnPhone] = useState(false);
  const [drawFor, setDrawFor] = useState(null);
  const [camera, setCamera] = useState(false);
  const [error, setError] = useState(null);
  const [board, setBoard] = useState(null);
  const [saving, setSaving] = useState(false);
  const [similarNote, setSimilarNote] = useState(null);
  const [now, setNow] = useState(Date.now());
  const [runId, setRunId] = useState(0);
  const urlRef = useRef(null);
  const desktop = useMedia('(min-width: 1000px)');

  const tags = useMemo(() => assignTags(obs), [obs]);
  const selected = obs.find((o) => o.id === selectedId) || null;
  const busy = BUSY.includes(a.phase);
  const hasResult = a.phase === 'done';

  const fail = useCallback((e) => {
    setError(e?.message || 'Something went wrong.');
    setA((p) => ({ ...p, phase: 'failed' }));
  }, []);

  const clearAnalysis = () => {
    setObs([]);
    setExtra({ findings: [], steps: [], concernsChecked: false });
    setMeta(null);
    setSelectedId(null);
    setDrawFor(null);
    setBoard(null);
  };

  const runAnalysis = useCallback(
    async (imageId) => {
      clearAnalysis();
      setError(null);
      setA({ phase: 'queued', startedAt: Date.now() });
      try {
        const { job_id } = await api.startAnalysis(imageId);
        setA((p) => ({ ...p, jobId: job_id, imageId }));
      } catch (e) {
        fail(e);
      }
    },
    [fail],
  );

  const setNewImage = (url, init) => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = url;
    setImage({ url, ...init });
  };

  async function handleFile(file) {
    setCamera(false);
    setError(null);
    clearAnalysis();
    setNewImage(URL.createObjectURL(file), { name: file.name, width: 0, height: 0, imageId: null, quality: null });
    setA({ phase: 'uploading', startedAt: Date.now() });
    try {
      const r = await api.uploadImage(file);
      setImage((i) => ({ ...i, width: r.width, height: r.height, imageId: r.image_id, quality: r.quality }));
      if (r.quality && r.quality.ok === false) {
        setA({ phase: 'idle' });
        return;
      }
      await runAnalysis(r.image_id);
    } catch (e) {
      fail(e);
    }
  }

  async function loadDemo() {
    setError(null);
    clearAnalysis();
    setA({ phase: 'uploading', startedAt: Date.now() });
    try {
      const r = await api.makeDemoImage();
      setNewImage(URL.createObjectURL(r.blob), { name: 'Synthetic demo board', width: r.width, height: r.height, imageId: r.image_id, quality: r.quality });
      await runAnalysis(r.image_id);
    } catch (e) {
      fail(e);
    }
  }

  // Poll the running job.
  useEffect(() => {
    if (!a.jobId || !['queued', 'running'].includes(a.phase)) return undefined;
    let stop = false;
    const id = setInterval(async () => {
      try {
        const r = await api.getAnalysis(a.jobId);
        if (stop) return;
        if (r.status === 'running') setA((p) => (p.phase === 'queued' ? { ...p, phase: 'running' } : p));
        if (r.status === 'done') {
          clearInterval(id);
          setObs(r.observations || []);
          setExtra({ findings: r.findings || [], steps: r.steps || [], concernsChecked: !!r.concerns_checked });
          setMeta({ model: r.model, adapter: r.adapter, is_mock: !!r.is_mock, latency: r.latency_s, attempts: r.attempts, dropped: r.dropped || [], detail: r.detail_pass || null, warnings: r.warnings || [] });
          setA((p) => ({ ...p, phase: 'done', finishedAt: Date.now() }));
          setRunId((n) => n + 1);
          const first = (r.observations || [])[0];
          setSelectedId(first ? first.id : null);
        } else if (r.status === 'failed') {
          clearInterval(id);
          setError(r.error?.message || 'The model did not return usable results. No detections are shown.');
          setA((p) => ({ ...p, phase: 'failed' }));
        } else if (r.status === 'cancelled') {
          clearInterval(id);
          setA((p) => ({ ...p, phase: 'cancelled' }));
        }
      } catch (e) {
        if (!stop) {
          clearInterval(id);
          fail(e);
        }
      }
    }, 700);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [a.jobId, a.phase, fail]);

  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [busy]);

  const cancel = async () => {
    try {
      if (a.jobId) await api.cancelAnalysis(a.jobId);
    } catch {
      /* the job may already have finished */
    }
    setA((p) => ({ ...p, phase: 'cancelled' }));
  };

  const newPhoto = () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
    setImage(null);
    clearAnalysis();
    setA({ phase: 'idle' });
    setError(null);
  };

  const onCorrect = async (id, patch) => {
    setSaving(true);
    setError(null);
    try {
      const r = await api.patchObservation(id, patch);
      setObs(r.observations || []);
      setExtra((x) => ({ findings: r.findings || [], steps: r.steps || [], concernsChecked: r.concerns_checked ?? x.concernsChecked }));
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const onSimilar = async (id) => {
    setSaving(true);
    setError(null);
    setSimilarNote(null);
    try {
      const r = await api.findSimilar(id);
      setObs(r.observations || []);
      setExtra((x) => ({ findings: r.findings || [], steps: r.steps || [], concernsChecked: r.concerns_checked ?? x.concernsChecked }));
      const n = (r.added || []).length;
      setSimilarNote({ id, text: n ? `Added ${n} look-alike${n === 1 ? '' : 's'}. Check each one: they are matched by appearance, not read.` : 'No other parts that look like this one were found.' });
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const onDraw = (box) => {
    const id = drawFor;
    setDrawFor(null);
    if (id) onCorrect(id, { bbox: box });
  };

  const onBoard = async (variant) => {
    try {
      const r = await api.confirmBoard(image.imageId, variant);
      setBoard(r.board_variant || variant);
      if (r.steps) setExtra((x) => ({ ...x, steps: r.steps }));
    } catch (e) {
      setError(e.message);
    }
  };

  const select = (id) => {
    setSelectedId(id);
    setTab('part');
    setPartsOnPhone(false);
  };

  const elapsed = ((a.finishedAt || now) - (a.startedAt || now)) / 1000;
  const quality = image?.quality;
  const needsDecision = image && quality && quality.ok === false && a.phase === 'idle';

  let statusText = 'Ready for a photo';
  if (a.phase === 'uploading') statusText = 'Uploading and checking the photo';
  if (a.phase === 'queued') statusText = 'Waiting for the model';
  if (a.phase === 'running') statusText = 'Reading the photo';
  if (a.phase === 'done') statusText = `Done in ${elapsed.toFixed(1)} s`;
  if (a.phase === 'failed') statusText = 'Analysis failed';
  if (a.phase === 'cancelled') statusText = 'Analysis cancelled';
  if (needsDecision) statusText = 'Photo needs a decision';

  const showPhone = !desktop;

  return (
    <div className="app" data-phone-parts={partsOnPhone ? 'true' : 'false'}>
      <header className="topbar">
        <div className="brand">
          <Mark />
          <span>VisionGuard</span>
        </div>
        <div className="topmeta">
          {meta && (
            <span className="chip-static" title="Model that produced this analysis">
              {meta.model}
            </span>
          )}
        </div>
      </header>

      {(isDemo || meta?.is_mock) && (
        <div className="banner" role="status">
          {isDemo
            ? 'Demo data. This is a drawn board with canned results, not an analysis of a real photo.'
            : 'Mock model. These results are canned test data, not an analysis of this photo.'}
        </div>
      )}

      <main className="main">
        <aside className="ledger-col" aria-label="Parts list">
          <Ledger observations={obs} tags={tags} selectedId={selectedId} onSelect={select} phase={a.phase} />
        </aside>

        <section className="center" aria-label="Photo">
          <div className="stagebar">
            <span className="fname" title={image?.name}>
              {image ? image.name : 'No photo yet'}
            </span>
            <span className="grow" />
            {image && (
              <>
                {busy ? (
                  <button className="btn" onClick={cancel}>
                    Cancel analysis
                  </button>
                ) : (
                  image.imageId && (
                    <button className="btn primary" onClick={() => runAnalysis(image.imageId)}>
                      {hasResult ? 'Analyze again' : 'Analyze'}
                    </button>
                  )
                )}
                <button className="btn" onClick={newPhoto} disabled={busy}>
                  New photo
                </button>
              </>
            )}
          </div>

          <div className="stagewrap">
            {!image && !camera && (
              <Intake onFile={handleFile} onCamera={() => setCamera(true)} onDemo={loadDemo} demo={isDemo} error={error} busy={busy} />
            )}
            {camera && <Camera onCapture={handleFile} onClose={() => setCamera(false)} />}
            {image && image.width > 0 && (
              <Canvas
                image={image}
                observations={obs}
                tags={tags}
                selectedId={selectedId}
                onSelect={select}
                drawFor={drawFor}
                onDraw={onDraw}
                onCancelDraw={() => setDrawFor(null)}
                analysisKey={runId}
                onMismatch={(m) => {
                  setError(m);
                  setA({ phase: 'failed' });
                }}
              />
            )}
            {image && image.width === 0 && <div className="working">Uploading and checking the photo</div>}

            {busy && image?.width > 0 && (
              <div className="working" role="status">
                <span className="scan" aria-hidden="true" />
                {a.phase === 'queued' ? 'Waiting for the model' : 'Reading the photo'}
                <span className="elapsed">{elapsed.toFixed(1)} s</span>
              </div>
            )}

            {needsDecision && (
              <div className="decision" role="alertdialog" aria-labelledby="q-title">
                <h2 id="q-title">This photo may be hard to read</h2>
                <ul className="plain">
                  {quality.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
                <div className="actions">
                  <button className="btn primary" onClick={newPhoto}>
                    Choose another photo
                  </button>
                  <button className="btn" onClick={() => runAnalysis(image.imageId)}>
                    Analyze anyway
                  </button>
                </div>
              </div>
            )}

            {error && image && (
              <div className="notice notice-error floating" role="alert">
                <span>{error}</span>
                <button className="linklike" onClick={() => setError(null)}>
                  Dismiss
                </button>
              </div>
            )}
          </div>
        </section>

        <aside className="inspector" aria-label="Inspector">
          <nav className="tabs" role="tablist" aria-label="Inspector sections">
            <button role="tab" aria-selected={showPhone && partsOnPhone} className={`tab only-phone${partsOnPhone ? ' on' : ''}`} onClick={() => setPartsOnPhone(true)}>
              Parts
            </button>
            {[
              ['part', 'Part'],
              ['findings', 'Findings'],
              ['steps', 'Steps'],
            ].map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key && !(showPhone && partsOnPhone)}
                className={`tab${tab === key && !(showPhone && partsOnPhone) ? ' on' : ''}`}
                onClick={() => {
                  setTab(key);
                  setPartsOnPhone(false);
                }}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="inspector-body">
            <div className="phone-parts">
              <Ledger observations={obs} tags={tags} selectedId={selectedId} onSelect={select} phase={a.phase} />
            </div>
            <div className="inspector-tabs">
              {tab === 'part' && image && image.width > 0 && (
                <Detail image={image} o={selected} tag={selected ? tags[selected.id] : null} onCorrect={onCorrect} onRedraw={() => setDrawFor(selected.id)} onSimilar={() => onSimilar(selected.id)} similarNote={similarNote && selected && similarNote.id === selected.id ? similarNote.text : null} saving={saving} />
              )}
              {tab === 'part' && !(image && image.width > 0) && (
                <div className="detail empty-detail" id="trace-anchor">
                  <h2>No part selected</h2>
                  <p className="empty">Add a photo and run an analysis. Details for the part you pick appear here.</p>
                </div>
              )}
              {tab === 'findings' && (
                <Findings observations={obs} findings={extra.findings} concernsChecked={extra.concernsChecked} tags={tags} onSelect={select} board={board} onBoard={onBoard} hasResult={hasResult} />
              )}
              {tab === 'steps' && <Steps steps={extra.steps} tags={tags} onSelect={select} hasResult={hasResult} />}
            </div>
          </div>
        </aside>
      </main>

      <footer className="statusbar" role="status">
        <span className={`dot ${a.phase}`} aria-hidden="true" />
        <span>{statusText}</span>
        {meta && (
          <>
            <span className="sep" />
            <span>{meta.adapter === 'demo' ? 'No model (demo)' : `${meta.model}`}</span>
            {meta.latency > 0 && <span>{meta.latency.toFixed(1)} s model time</span>}
            {meta.attempts > 1 && <span>{meta.attempts} attempts</span>}
            {meta.dropped.length > 0 && <span>{meta.dropped.length} invalid items dropped</span>}
            {meta.warnings?.length > 0 && <span className="warn" title={meta.warnings.join('\n')}>{meta.warnings.length === 1 ? meta.warnings[0] : `${meta.warnings.length} warnings, hover for details`}</span>}
            {meta.detail && meta.detail.attempted > 0 && (
              <span>
                Close-up read: {meta.detail.read} of {meta.detail.attempted} chips
                {meta.detail.failed > 0 ? `, ${meta.detail.failed} failed` : ''}
              </span>
            )}
          </>
        )}
      </footer>

      <Trace selectedId={selectedId} enabled={desktop && tab === 'part' && !!image && image.width > 0 && !!selected} />
    </div>
  );
}
