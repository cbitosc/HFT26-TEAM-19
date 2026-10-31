// DEMO ONLY. A drawn, synthetic board plus canned results so the interface can be reviewed
// without a model. Nothing here is analysis of a real photo, and the UI says so persistently.

const W = 1600;
const H = 1000;

function drawBoard() {
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const g = c.getContext('2d');

  g.fillStyle = '#242421';
  g.fillRect(0, 0, W, H);
  // board
  g.fillStyle = '#1d6a49';
  g.fillRect(140, 110, 1320, 780);
  g.strokeStyle = '#2b8560';
  g.lineWidth = 6;
  g.strokeRect(150, 120, 1300, 760);
  // traces
  g.strokeStyle = '#2f9166';
  g.lineWidth = 7;
  const lines = [
    [[330, 250], [330, 400], [540, 560]],
    [[880, 560], [990, 520]],
    [[1180, 520], [1300, 520], [1340, 505]],
    [[700, 740], [700, 820], [1090, 820], [1090, 755]],
    [[420, 655], [540, 655]],
  ];
  lines.forEach((pts) => {
    g.beginPath();
    pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    g.stroke();
  });
  // holes
  [[190, 160], [1410, 160], [190, 840], [1410, 840]].forEach(([x, y]) => {
    g.fillStyle = '#242421';
    g.beginPath();
    g.arc(x, y, 18, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = '#d4b45a';
    g.lineWidth = 5;
    g.stroke();
  });
  // silkscreen note
  g.fillStyle = '#e8e6da';
  g.font = '600 22px sans-serif';
  g.fillText('SYNTHETIC DEMO BOARD', 600, 880 - 10);

  // 2x20 header
  g.fillStyle = '#101010';
  g.fillRect(300, 160, 1000, 82);
  for (let i = 0; i < 20; i++) {
    for (let r = 0; r < 2; r++) {
      g.fillStyle = '#d4b45a';
      g.fillRect(318 + i * 49, 176 + r * 34, 16, 16);
    }
  }
  // QFP IC with readable marking
  g.fillStyle = '#d6d6d6';
  for (let i = 0; i < 12; i++) {
    const o = 560 + i * 24;
    g.fillRect(o, 404, 8, 22);
    g.fillRect(o, 714, 8, 22);
    g.fillRect(544, 430 + i * 24, 22, 8);
    g.fillRect(854, 430 + i * 24, 22, 8);
  }
  g.fillStyle = '#141414';
  g.fillRect(568, 428, 284, 284);
  g.fillStyle = '#b9b9b0';
  g.font = '600 38px monospace';
  g.fillText('ZK2040', 622, 556);
  g.fillText('4417A', 640, 610);
  g.beginPath();
  g.arc(598, 458, 9, 0, Math.PI * 2);
  g.fillStyle = '#6b6b66';
  g.fill();
  // SOIC with smudged marking
  g.fillStyle = '#d6d6d6';
  for (let i = 0; i < 4; i++) {
    g.fillRect(1004 + i * 42, 460, 10, 16);
    g.fillRect(1004 + i * 42, 554, 10, 16);
  }
  g.fillStyle = '#161616';
  g.fillRect(996, 474, 190, 82);
  g.strokeStyle = 'rgba(190,190,180,0.45)';
  g.lineWidth = 3;
  for (let i = 0; i < 5; i++) {
    g.beginPath();
    g.moveTo(1014 + i * 32, 500 + (i % 2) * 6);
    g.bezierCurveTo(1024 + i * 32, 488, 1030 + i * 32, 526, 1038 + i * 32, 514);
    g.stroke();
  }
  // USB port
  g.fillStyle = '#c9ccd0';
  g.fillRect(104, 420, 132, 136);
  g.fillStyle = '#7f8388';
  g.fillRect(128, 446, 90, 84);
  g.fillStyle = '#2a2a28';
  g.fillRect(140, 478, 70, 20);
  // electrolytic cap C
  g.fillStyle = '#26333f';
  g.beginPath();
  g.arc(1250, 700, 56, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = '#e0e0d8';
  g.fillRect(1205, 660, 14, 80);
  g.fillStyle = '#9fa9b3';
  g.beginPath();
  g.arc(1250, 700, 34, 0, Math.PI * 2);
  g.fill();
  // second cap with discoloured patch
  g.fillStyle = '#5b4426';
  g.beginPath();
  g.arc(1090, 722, 56, 0, Math.PI * 2);
  g.globalAlpha = 0.5;
  g.fill();
  g.globalAlpha = 1;
  g.fillStyle = '#26333f';
  g.beginPath();
  g.arc(1090, 720, 32, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = '#e0e0d8';
  g.fillRect(1066, 700, 8, 42);
  // resistor
  g.fillStyle = '#cdb98e';
  g.fillRect(350, 640, 70, 30);
  g.fillStyle = '#9aa0a5';
  g.fillRect(344, 640, 10, 30);
  g.fillRect(416, 640, 10, 30);
  // LED
  g.fillStyle = '#c24a3d';
  g.beginPath();
  g.arc(330, 780, 24, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = 'rgba(255,255,255,0.35)';
  g.beginPath();
  g.arc(322, 772, 8, 0, Math.PI * 2);
  g.fill();
  // button
  g.fillStyle = '#2a2a28';
  g.fillRect(1300, 420, 80, 80);
  g.fillStyle = '#6e7377';
  g.beginPath();
  g.arc(1340, 460, 26, 0, Math.PI * 2);
  g.fill();

  return new Promise((resolve) => c.toBlob((b) => resolve(b), 'image/jpeg', 0.92));
}

const OBS = (n, category, bbox, extra = {}) => ({
  id: `obs_${String(n).padStart(3, '0')}`,
  image_id: 'demo',
  frame_id: null,
  category,
  marking_text: null,
  candidates: [],
  bbox,
  bbox_space: 'original_px',
  status: 'unknown',
  evidence: [],
  limitations: [],
  reference_ids: [],
  model_score: null,
  model_score_note: 'uncalibrated',
  source: 'vlm',
  ...extra,
});

const initial = () => [
  OBS(0, 'ic_package', [540, 400, 880, 740], {
    marking_text: 'ZK2040 4417A',
    status: 'tentative',
    evidence: ['Model saw: square chip with printed text', 'Marking read by the model (unverified): ZK2040 4417A'],
    limitations: ['No matching reference in the local library'],
    model_score: 0.7,
  }),
  OBS(1, 'ic_package', [990, 455, 1190, 575], {
    evidence: ['Model saw: small eight-pin chip'],
    limitations: ['Marking not readable in this view', 'Take a close-up with light from the side'],
  }),
  OBS(2, 'gpio_header', [295, 155, 1305, 248], {
    evidence: ['Model saw: two rows of pins along the top edge'],
    limitations: ['Board variant not confirmed, so pin names are not shown'],
  }),
  OBS(3, 'usb_port', [100, 415, 240, 560], { evidence: ['Model saw: metal USB shell on the left edge'] }),
  OBS(4, 'capacitor', [1190, 640, 1310, 760], { evidence: ['Model saw: cylindrical capacitor with polarity stripe'] }),
  OBS(5, 'capacitor', [1030, 662, 1150, 782], {
    evidence: ['Model saw: capacitor with a darker area around its base'],
    limitations: ['Colour in a photo depends on the light'],
  }),
  OBS(6, 'resistor', [338, 630, 432, 680], { evidence: ['Model saw: small tan surface-mount part'] }),
  OBS(7, 'led', [300, 750, 360, 810], { evidence: ['Model saw: red dome'] }),
  OBS(8, 'button', [1295, 415, 1385, 505], { evidence: ['Model saw: square push button'] }),
];

const FINDINGS = [
  {
    id: 'f_demo_1',
    kind: 'suspected',
    title: 'Darker area around the base of C2',
    detail: 'The board next to this capacitor looks browner than the rest of the board in this view.',
    verify_by: 'Look again in bright, even light from two angles before drawing a conclusion.',
    observation_ids: ['obs_005'],
  },
];

const STEPS = [
  {
    id: 's_demo_1',
    text: 'Disconnect power and confirm the board is unpowered.',
    expect: 'No LED lit, nothing plugged in.',
    requires_measurement: false,
    observation_ids: [],
  },
  {
    id: 's_demo_2',
    text: 'Look at C2 from the side in bright light.',
    expect: 'A flat top and no residue around the base.',
    requires_measurement: false,
    observation_ids: ['obs_005'],
  },
  {
    id: 's_demo_3',
    text: 'Record the reading from your own check of the C2 pads (board unpowered).',
    expect: 'Write down the value; compare it with the capacitor datasheet.',
    requires_measurement: true,
    unit: 'ohm',
    observation_ids: ['obs_005'],
  },
];

let store = { obs: initial(), polls: 0, board: null };

export const demoApi = {
  async health() {
    return { demo: true };
  },
  async uploadImage() {
    throw Object.assign(new Error('Demo mode has no model. Use the demo board, or run the backend for real photos.'), {
      code: 'demo_no_upload',
    });
  },
  async makeDemoImage() {
    const blob = await drawBoard();
    store = { obs: initial(), polls: 0, board: null };
    return { blob, width: W, height: H, image_id: 'demo', quality: { ok: true, problems: [] } };
  },
  async startAnalysis() {
    store.polls = 0;
    return { job_id: 'demo-job' };
  },
  async getAnalysis() {
    store.polls += 1;
    await new Promise((r) => setTimeout(r, 250));
    if (store.polls < 3) return { status: store.polls < 2 ? 'queued' : 'running' };
    return {
      status: 'done',
      model: 'DEMO (no model)',
      adapter: 'demo',
      is_mock: true,
      latency_s: 0,
      attempts: 1,
      dropped: [],
      observations: store.obs,
      findings: FINDINGS,
      concerns_checked: true,
      steps: STEPS,
    };
  },
  async cancelAnalysis() {
    return { status: 'cancelled' };
  },
  async patchObservation(id, patch) {
    store.obs = store.obs.map((o) => {
      if (o.id !== id) return o;
      const next = { ...o };
      if (patch.category) next.category = patch.category;
      if ('marking_text' in patch) next.marking_text = patch.marking_text || null;
      if ('identity' in patch) next.candidates = patch.identity ? [{ identity: patch.identity, reference_id: null }] : [];
      if (patch.bbox) next.bbox = patch.bbox;
      if (patch.confirmed) {
        next.status = 'confirmed';
        next.source = 'user';
      } else if (next.marking_text) {
        next.status = o.status === 'confirmed' ? 'confirmed' : 'tentative';
      } else if (!patch.confirmed) {
        next.status = 'unknown';
        next.candidates = [];
      }
      if (patch.bbox || patch.category) next.source = 'user';
      return next;
    });
    // A correction invalidates dependent guidance (real backend regenerates it).
    return { observations: store.obs, findings: [], concerns_checked: true, steps: [] };
  },
  async findSimilar() {
    return { observations: store.obs, findings: [], concerns_checked: true, steps: [], added: [], similar: { exemplars: 1, found: 0 } };
  },
  async confirmBoard(_imageId, variant) {
    store.board = variant;
    return { board_variant: variant };
  },
};
