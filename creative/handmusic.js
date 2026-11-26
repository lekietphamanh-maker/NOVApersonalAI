// Hand Music: pure gesture-to-music logic for creative mode. No DOM, no audio, so it runs under `node --test`.
//
// Adapted from the *patterns* in ewanqian/performable-music, spatial-playground/hand-osc-lab/
// (engine.mjs + instrument-gesture.mjs) — no code copied verbatim, and the input is different:
// that lab reads 25-joint WebXR hands from a headset; Nova reads MediaPipe's 21 landmarks from a
// webcam (wrist 0, thumb 1-4, index 5-8, middle 9-12, ring 13-16, pinky 17-20).
//
// Two deliberate differences from the lab, both because a webcam is noisier than a headset:
//  - Distances are measured in *palm units* (gap / wrist-to-middle-knuckle), not metres. A palm is
//    ~85 mm, so the lab's 28 mm press / 43 mm release is 0.33 / 0.51 palms — the same thresholds
//    Nova's creative mode already uses for pinch (gestures.js: 0.35 / 0.5).
//  - Zones live in screen fractions (the fingertip you see on screen), not metres in XR space.

/** Default zones (their notes and pans are ZONE_PINGS in handmusic-audio.js): centre x/y as fractions of screen width/height, radius as a fraction of screen height. */
export function defaultZones() {
  return [
    { id: "A", name: "LEFT FIELD", cx: 0.2, cy: 0.42, r: 0.16 },
    { id: "B", name: "RIGHT FIELD", cx: 0.8, cy: 0.42, r: 0.16 },
    { id: "C", name: "CENTER TRIGGER", cx: 0.5, cy: 0.26, r: 0.14 },
  ];
}

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, Number.isFinite(v) ? v : a));

/** Distance between two landmarks, in palm units (1 palm = wrist to middle knuckle). */
export function palmDistance(landmarks, a, b) {
  if (!Array.isArray(landmarks) || landmarks.length < 21) return null;
  const palm = Math.hypot(landmarks[0].x - landmarks[9].x, landmarks[0].y - landmarks[9].y);
  if (!(palm > 1e-6)) return null;
  return Math.hypot(landmarks[a].x - landmarks[b].x, landmarks[a].y - landmarks[b].y) / palm;
}

// ---------- zones ----------
//
// The safety rules are the whole point (from the lab's ZoneEngine):
//  - hysteresis: you must go a little *inside* to enter, a little *outside* to exit, so a fingertip
//    hovering on the edge doesn't flutter;
//  - dwell: the fingertip must stay past the edge for a short time before the event fires;
//  - tracking loss is UNKNOWN: it never fabricates an EXIT. A vanished hand reports TRACKING_LOST
//    and the zone simply stops being "inside" — the synth then fades, it never gets a note-off it
//    didn't earn.
//
// Webcam frames arrive at ~30 fps, not the lab's 90 Hz, so the dwell is 50 ms (~2 frames) and the
// loss window is 200 ms (~6 frames): a single dropped frame must not count as losing the hand.
export function createZoneEngine(zones = defaultZones(), options = {}) {
  const enterMargin = options.enterMargin ?? 0.012;
  const exitMargin = options.exitMargin ?? 0.02;
  const dwellMs = options.dwellMs ?? 50;
  const missingMs = options.missingMs ?? 200;
  const states = new Map();
  return {
    zones,
    update(hand, point, now, aspect = 16 / 9) {
      const events = [];
      for (const z of zones) {
        const key = `${hand}:${z.id}`;
        let s = states.get(key);
        if (!s) { s = { inside: false, pending: null, since: now, lastSeen: now }; states.set(key, s); }
        if (!point) {
          if (now - s.lastSeen >= missingMs) {
            // Loss of tracking is UNKNOWN, never fabricate an EXIT.
            if (s.inside || s.pending !== null) events.push({ zone: z.id, hand, type: "TRACKING_LOST", t_ms: now });
            s.inside = false; s.pending = null; s.lastSeen = now;
          }
          continue;
        }
        s.lastSeen = now;
        const d = Math.hypot((point.x - z.cx) * aspect, point.y - z.cy);
        const goal = s.inside ? d < z.r + exitMargin : d < z.r - enterMargin;
        if (goal === s.inside) { s.pending = null; continue; }
        if (s.pending !== goal) { s.pending = goal; s.since = now; continue; }
        if (now - s.since >= dwellMs) {
          s.inside = goal; s.pending = null;
          events.push({ zone: z.id, hand, type: goal ? "ENTER" : "EXIT", t_ms: now, distance: +d.toFixed(4) });
        }
      }
      return events;
    },
    isInside(hand, zoneId) { return states.get(`${hand}:${zoneId}`)?.inside ?? false; },
    reset() { states.clear(); },
  };
}

// ---------- gesture -> sound ----------
//
// Mapping, adapted from the lab's instrument-gesture.mjs into palm units:
//  - right thumb-index pinch (hysteresis) = note gate; left pinch works alone if the right hand is away
//  - thumb-index distance = filter cutoff (open hand = bright, pinched = dark)
//  - thumb-middle distance = resonance, thumb-ring = delay wet, thumb-pinky = drive
//  - distance between the two index tips = stereo spread
//  - wrist height = energy/volume (hand raised = louder)
//  - index tip touching middle PIP = next voice
// Continuous values are exponentially smoothed (45 ms time constant, as in the lab) so the sound
// doesn't jitter with the webcam.
const PINCH_ON = 0.35;  // palm units: same as Nova's pinch in gestures.js, and ~28 mm on a real hand
const PINCH_OFF = 0.5;  // ~43 mm: the release edge, so a pinch doesn't flutter
const INITIAL = { gate: false, leftPinch: false, rightPinch: false, lastTimbre: -Infinity, timbre: 0, lastTime: null,
  cutoff: 0.45, wet: 0.14, spread: 0.5, energy: 0.25, drive: 0.12, resonance: 0.3 };

export function createHandMusicInstrument(options = {}) {
  const cooldownMs = options.cooldownMs ?? 380;
  const timeConstantMs = options.timeConstantMs ?? 45;
  const state = { ...INITIAL };
  const reset = () => Object.assign(state, INITIAL);
  return {
    get state() { return { ...state }; },
    setTimbre(value) { state.timbre = Math.round(Math.min(2, Math.max(0, Number(value) || 0))); },
    reset,
    update({ left = null, right = null, zoneEvents = [], now = 0 } = {}) {
      const events = [];
      const pinchGap = (hand) => (hand ? palmDistance(hand, 4, 8) : null);
      const pinch = (hand, prior) => {
        const d = pinchGap(hand);
        return d !== null && (prior ? d < PINCH_OFF : d <= PINCH_ON);
      };
      state.leftPinch = pinch(left, state.leftPinch);
      state.rightPinch = pinch(right, state.rightPinch);
      state.gate = state.rightPinch || (!right && state.leftPinch);
      const controlling = right || left;
      const finger = (tip) => (controlling ? palmDistance(controlling, 4, tip) : null);
      const contact = (dist) => (dist === null ? 0 : clamp((0.65 - dist) / 0.45));
      const middle = contact(finger(12)), ring = contact(finger(16)), pinky = contact(finger(20));
      const indexGap = pinchGap(controlling);
      const rawCutoff = indexGap === null ? 0.45 : clamp((indexGap - 0.2) / 1.2);
      const spreadGap = left && right ? (() => {
        const palm = Math.hypot(left[0].x - left[9].x, left[0].y - left[9].y);
        if (!(palm > 1e-6)) return null;
        return Math.hypot(left[8].x - right[8].x, left[8].y - right[8].y) / palm;
      })() : null;
      // Inter-hand distance needs both hands' palms as the yardstick: use the left hand's palm.
      const spreadRaw = spreadGap === null ? 0.5 : clamp((spreadGap - 0.5) / 3.0);
      const wristY = controlling?.[0]?.y;
      const rawEnergy = Number.isFinite(wristY) ? clamp((0.8 - wristY) / 0.6) : 0.25;
      const targets = {
        cutoff: rawCutoff, wet: 0.08 + ring * 0.44, spread: spreadRaw, energy: rawEnergy,
        drive: 0.12 + 0.68 * pinky, resonance: 0.16 + middle * 0.78,
      };
      const dt = state.lastTime === null ? 16 : clamp(now - state.lastTime, 0, 200);
      state.lastTime = now;
      const alpha = 1 - Math.exp(-dt / timeConstantMs);
      for (const key of Object.keys(targets)) state[key] += alpha * (targets[key] - state[key]);
      // Index tip touching the middle finger's PIP joint (landmark 10) cycles the voice.
      const cross = controlling ? palmDistance(controlling, 8, 10) : null;
      if (cross !== null && cross <= 0.3 && now - state.lastTimbre >= cooldownMs) {
        state.timbre = (state.timbre + 1) % 3; state.lastTimbre = now;
        events.push({ type: "TIMBRE_CHANGE", value: state.timbre, t_ms: now });
      }
      for (const ev of zoneEvents) {
        if (!["A", "B", "C"].includes(ev?.zone) || !["left", "right"].includes(ev?.hand)) continue;
        if (ev.type === "ENTER" || ev.type === "EXIT") events.push({ type: `ZONE_${ev.type}`, zone: ev.zone, hand: ev.hand, t_ms: now });
        else if (ev.type === "TRACKING_LOST") events.push({ type: "ZONE_LOST", zone: ev.zone, hand: ev.hand, t_ms: now });
      }
      return {
        params: {
          gate: state.gate ? 1 : 0, cutoff: clamp(state.cutoff), wet: clamp(state.wet),
          spread: clamp(state.spread), energy: clamp(state.energy), drive: clamp(state.drive),
          resonance: clamp(state.resonance), timbre: state.timbre,
        },
        events,
      };
    },
  };
}
