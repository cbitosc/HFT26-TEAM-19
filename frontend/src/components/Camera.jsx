import { useEffect, useRef, useState } from 'react';

function explain(err) {
  if (!window.isSecureContext) {
    return 'The browser only allows the camera on a secure page. Open the app at http://localhost, or use the USB setup in the docs on a phone.';
  }
  switch (err?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera access was blocked. Allow the camera for this site in the browser address bar, then try again.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'No camera was found. Connect a camera or choose a photo instead.';
    case 'NotReadableError':
      return 'The camera is in use by another app. Close that app and try again.';
    default:
      return 'The camera could not be started. Choose a photo instead.';
  }
}

export default function Camera({ onCapture, onClose }) {
  const video = useRef(null);
  const stream = useRef(null);
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState('');
  const [error, setError] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      setReady(false);
      setError(null);
      stream.current?.getTracks().forEach((t) => t.stop());
      if (!navigator.mediaDevices?.getUserMedia) {
        setError(explain(null));
        return;
      }
      try {
        const constraints = {
          video: deviceId
            ? { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 } }
            : { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        };
        const s = await navigator.mediaDevices.getUserMedia(constraints);
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        stream.current = s;
        if (video.current) {
          video.current.srcObject = s;
          await video.current.play().catch(() => {});
        }
        const list = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
        if (!cancelled) {
          setDevices(list);
          setReady(true);
        }
      } catch (e) {
        if (!cancelled) setError(explain(e));
      }
    }
    start();
    return () => {
      cancelled = true;
    };
  }, [deviceId]);

  useEffect(
    () => () => {
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  function capture() {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);
    c.toBlob(
      (blob) => {
        if (!blob) return;
        stream.current?.getTracks().forEach((t) => t.stop());
        onCapture(new File([blob], `capture-${Date.now()}.jpg`, { type: 'image/jpeg' }));
      },
      'image/jpeg',
      0.92,
    );
  }

  return (
    <div className="camera">
      {error ? (
        <div className="camera-error">
          <h2>Camera unavailable</h2>
          <p role="alert">{error}</p>
          <button className="btn primary" onClick={onClose}>
            Choose a photo instead
          </button>
        </div>
      ) : (
        <>
          <video ref={video} playsInline muted aria-label="Camera preview" />
          <div className="camera-bar">
            {devices.length > 1 && (
              <label className="field inline">
                <span>Camera</span>
                <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                  <option value="">Automatic (rear camera if available)</option>
                  {devices.map((d, i) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Camera ${i + 1}`}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <span className="grow" />
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn primary" onClick={capture} disabled={!ready}>
              Capture photo
            </button>
          </div>
        </>
      )}
    </div>
  );
}
