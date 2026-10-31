export const CATEGORY_LABEL = {
  ic_package: 'IC',
  microcontroller_module: 'Microcontroller module',
  gpio_header: 'Pin header',
  connector: 'Connector',
  usb_port: 'USB port',
  capacitor: 'Capacitor',
  resistor: 'Resistor',
  led: 'LED',
  button: 'Button',
  wire: 'Wire',
  board: 'Board',
  other: 'Part',
};

export const CATEGORIES = Object.keys(CATEGORY_LABEL);

// Board-style tag prefixes. These are VisionGuard's own numbering, not text read from the board.
const PREFIX = {
  ic_package: 'U',
  microcontroller_module: 'M',
  gpio_header: 'J',
  connector: 'J',
  usb_port: 'J',
  capacitor: 'C',
  resistor: 'R',
  led: 'D',
  button: 'SW',
  wire: 'W',
  board: 'BRD',
  other: 'X',
};

/** Stable tags: numbered in observation-id order per prefix, so a correction never renumbers others. */
export function assignTags(observations) {
  const counters = {};
  const tags = {};
  [...observations]
    .sort((a, b) => a.id.localeCompare(b.id))
    .forEach((o) => {
      const p = PREFIX[o.category] || 'X';
      counters[p] = (counters[p] || 0) + 1;
      tags[o.id] = `${p}${counters[p]}`;
    });
  return tags;
}

export function nameFor(o) {
  if (o.marking_text) return o.marking_text;
  const guess = o.candidates?.[0]?.identity;
  if (guess) return guess;
  const label = CATEGORY_LABEL[o.category] ?? 'Part';
  // Keep acronyms (IC, LED, USB) as written; lower-case only the ordinary words.
  const shown = label.split(' ').map((w) => (w === w.toUpperCase() ? w : w.toLowerCase())).join(' ');
  return `Unidentified ${shown}`;
}

export const STATUS_WORD = {
  confirmed: 'Confirmed',
  tentative: 'Tentative',
  unknown: 'Not identified',
};

export const BOARD_VARIANTS = [
  'Raspberry Pi 40-pin header board',
  'Arduino Uno R3',
  'ESP32 DevKit V1 (30-pin)',
  'Other or unsupported board',
];
