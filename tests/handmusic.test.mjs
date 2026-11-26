// Run: node --test tests/handmusic.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { createHandMusicInstrument, createZoneEngine, defaultZones, palmDistance } from "../creative/handmusic.js";
import { ZONE_PINGS } from "../creative/handmusic-audio.js";

/** A flat hand: wrist at (0.5, 0.8), middle knuckle 0.2 above it, thumb and index tips `gap` apart (palm units: palm = 0.2). */
function hand(gapPalm = 1, wristY = 0.8) {
  const gap = gapPalm * 0.2;
  // A plausible flat hand: each finger is a short chain going up, so every bend is defined.
  const points = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.6, z: 0 }));
  points[0] = { x: 0.5, y: wristY, z: 0 };
  points[1] = { x: 0.45, y: 0.7, z: 0 }; points[2] = { x: 0.42, y: 0.62, z: 0 }; points[3] = { x: 0.4, y: 0.55, z: 0 };
  points[5] = { x: 0.48, y: 0.62, z: 0 }; points[6] = { x: 0.48, y: 0.55, z: 0 }; points[7] = { x: 0.48, y: 0.48, z: 0 };
  points[9] = { x: 0.5, y: 0.6, z: 0 }; points[10] = { x: 0.5, y: 0.52, z: 0 }; points[11] = { x: 0.5, y: 0.44, z: 0 };
  points[13] = { x: 0.53, y: 0.62, z: 0 }; points[14] = { x: 0.54, y: 0.55, z: 0 }; points[15] = { x: 0.55, y: 0.48, z: 0 };
  points[17] = { x: 0.56, y: 0.64, z: 0 }; points[18] = { x: 0.58, y: 0.58, z: 0 }; points[19] = { x: 0.6, y: 0.52, z: 0 };
  points[4] = { x: 0.5 - gap / 2, y: 0.5, z: 0 };
  points[8] = { x: 0.5 + gap / 2, y: 0.5, z: 0 };
  points[12] = { x: 0.62, y: 0.5, z: 0 };
  points[16] = { x: 0.66, y: 0.5, z: 0 };
  points[20] = { x: 0.7, y: 0.5, z: 0 };
  return points;
}

/** Deterministic pseudo-random: same jitter every run, so the thresholds are testable. */
function rng(seed) {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

test("palmDistance measures in palm units", () => {
  assert.ok(Math.abs(palmDistance(hand(1), 4, 8) - 1) < 1e-9);
  assert.ok(Math.abs(palmDistance(hand(0.3), 4, 8) - 0.3) < 1e-9);
  assert.equal(palmDistance(null, 4, 8), null);
});

test("zone ENTER needs the dwell, and the fingertip must go past the enter margin", () => {
  const engine = createZoneEngine();
  const zone = defaultZones()[0]; // A: centre (0.2, 0.42), r 0.16
  const inside = { x: zone.cx, y: zone.cy };
  const edge = { x: zone.cx + (zone.r - 0.006) / (16 / 9), y: zone.cy }; // inside the circle, outside the enter margin
  assert.deepEqual(engine.update("right", edge, 0), []);
  assert.deepEqual(engine.update("right", edge, 1000), []); // hovering on the edge never enters
  assert.deepEqual(engine.update("right", inside, 2000), []); // dwell not yet met
  const events = engine.update("right", inside, 2060);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "ENTER");
  assert.equal(events[0].zone, "A");
});

test("zone hysteresis: once inside, the fingertip must go past the exit margin to leave", () => {
  const engine = createZoneEngine();
  const zone = defaultZones()[0];
  const inside = { x: zone.cx, y: zone.cy };
  engine.update("right", inside, 0);
  engine.update("right", inside, 60);
  // Just outside the circle but inside the exit margin: still inside.
  const rim = { x: zone.cx + (zone.r + 0.01) / (16 / 9), y: zone.cy };
  assert.deepEqual(engine.update("right", rim, 200), []);
  assert.deepEqual(engine.update("right", rim, 2000), []);
  // Past the exit margin: EXIT after the dwell, not before.
  const out = { x: zone.cx + (zone.r + 0.03) / (16 / 9), y: zone.cy };
  assert.deepEqual(engine.update("right", out, 3000), []);
  const events = engine.update("right", out, 3060);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "EXIT");
});

test("tracking loss never fabricates an EXIT: it reports TRACKING_LOST", () => {
  const engine = createZoneEngine();
  const zone = defaultZones()[0];
  const inside = { x: zone.cx, y: zone.cy };
  engine.update("right", inside, 0);
  engine.update("right", inside, 60);
  assert.deepEqual(engine.update("right", null, 100), []); // one dropped frame: nothing
  const events = engine.update("right", null, 300); // 200 ms with no hand
  assert.equal(events.length, 1);
  assert.equal(events[0].type, "TRACKING_LOST");
  assert.ok(!events.some((e) => e.type === "EXIT"));
  // The zone un-sticks: it is no longer inside, and a longer absence reports nothing more.
  assert.equal(engine.isInside("right", "A"), false);
  assert.deepEqual(engine.update("right", null, 600), []);
  // And the zone is forgotten: re-entering needs the dwell again.
  assert.deepEqual(engine.update("right", inside, 700), []);
  assert.equal(engine.update("right", inside, 760)[0].type, "ENTER");
});

test("each zone rings its own note, panned to where it sits on screen", () => {
  const zones = defaultZones();
  assert.deepEqual(ZONE_PINGS.map((ping) => ping.zone), zones.map((zone) => zone.id));
  for (const zone of zones) {
    const ping = ZONE_PINGS.find((p) => p.zone === zone.id);
    assert.equal(Math.sign(ping.pan), Math.sign(Math.round((zone.cx - 0.5) * 10)), zone.id); // left zone pans left, centre stays centre
  }
  assert.ok(new Set(ZONE_PINGS.map((ping) => ping.freq)).size === ZONE_PINGS.length);
});

test("pinch gate has hysteresis and opens the filter as the hand opens", () => {
  const music = createHandMusicInstrument();
  let out = music.update({ right: hand(0.2), now: 0 }); // gap 0.2 palms: closed
  assert.equal(out.params.gate, 1);
  out = music.update({ right: hand(0.4), now: 100 }); // 0.4: stays closed
  assert.equal(out.params.gate, 1);
  out = music.update({ right: hand(0.6), now: 200 }); // 0.6: opens
  assert.equal(out.params.gate, 0);
  // Cutoff follows the thumb-index gap, smoothed: an open hand is brighter than a pinched one.
  const closed = createHandMusicInstrument().update({ right: hand(0.2), now: 0 }).params.cutoff;
  const open = createHandMusicInstrument().update({ right: hand(1.2), now: 0 }).params.cutoff;
  assert.ok(open > closed);
});

test("no hands means no gate, and a pinched left hand plays only while the right is away", () => {
  const music = createHandMusicInstrument();
  assert.equal(music.update({ left: hand(0.2), right: hand(0.2), now: 0 }).params.gate, 1);
  assert.equal(music.update({ now: 100 }).params.gate, 0); // both hands vanish
  assert.equal(music.update({ left: hand(0.2), now: 200 }).params.gate, 1);
  assert.equal(music.update({ left: hand(0.2), right: hand(1.2), now: 300 }).params.gate, 0); // the open right hand rules
});

test("the voice cycles on index-to-middle contact, then a cooldown blocks a repeat", () => {
  const music = createHandMusicInstrument();
  const touching = hand(1);
  touching[8] = { ...touching[10] };
  let out = music.update({ right: touching, now: 1000 });
  assert.ok(out.events.some((e) => e.type === "TIMBRE_CHANGE" && e.value === 1));
  out = music.update({ right: touching, now: 1100 });
  assert.ok(!out.events.some((e) => e.type === "TIMBRE_CHANGE"));
});

test("reset puts the instrument back to its starting sound", () => {
  const music = createHandMusicInstrument();
  music.update({ right: hand(1.2, 0.3), now: 0 });
  music.setTimbre(2);
  music.reset();
  const { state } = music;
  assert.equal(state.timbre, 0);
  assert.equal(state.gate, false);
  assert.equal(state.cutoff, 0.45);
  assert.equal(state.lastTime, null);
});

test("continuous values smooth toward their target instead of jumping", () => {
  const music = createHandMusicInstrument();
  const first = music.update({ right: hand(1.2), now: 0 }).params.cutoff;
  const second = music.update({ right: hand(1.2), now: 16 }).params.cutoff;
  assert.ok(second > first); // still climbing toward the open-hand target
  assert.ok(second < 0.9); // not there yet after one frame
});

test("wrist height sets energy: raised hand is louder than lowered hand", () => {
  const high = createHandMusicInstrument().update({ right: hand(1, 0.3), now: 0 }).params.energy;
  const low = createHandMusicInstrument().update({ right: hand(1, 0.85), now: 0 }).params.energy;
  assert.ok(high > low);
});

// ---------- webcam jitter: what the thresholds were tuned against ----------
//
// There is no camera in this VM, so the jitter numbers come from MediaPipe's own behaviour:
// a stationary hand's landmarks wander ~0.002-0.005 in normalized frame units per frame, and the
// One Euro filter in gestures.js already smooths that before it reaches this module. These tests
// feed a stationary hand with Gaussian noise at sigma 0.005 (the pessimistic end) for 10 seconds
// at 30 fps and require zero false triggers — that is the measurement the thresholds stand on.
// The noise generator is seeded, so the test is deterministic.
function noisyHand(base, random, sigma) {
  const gauss = () => (random() + random() + random() + random() - 2) * 1.2 * sigma;
  return base.map((p) => ({ x: p.x + gauss(), y: p.y + gauss(), z: 0 }));
}

test("jitter: a still open hand triggers no pinch and no zone for 10 seconds", () => {
  const random = rng(42);
  const music = createHandMusicInstrument();
  const engine = createZoneEngine();
  const zone = defaultZones()[1]; // B, right side; the hand rests centre-frame, far from it
  let falseEvents = 0;
  for (let frame = 0; frame < 300; frame++) {
    const now = frame * 33;
    const noisy = noisyHand(hand(1.0), random, 0.005);
    const out = music.update({ right: noisy, now });
    if (out.params.gate === 1) falseEvents++;
    const tip = { x: noisy[8].x, y: noisy[8].y };
    if (engine.update("right", tip, now).length > 0) falseEvents++;
  }
  assert.equal(falseEvents, 0);
});

test("jitter: a hand resting just outside a zone edge does not enter it", () => {
  const random = rng(7);
  const engine = createZoneEngine();
  const zone = defaultZones()[0];
  // Fingertip parked just outside the enter margin, on the rim of zone A.
  const park = { x: zone.cx + (zone.r - 0.002) / (16 / 9), y: zone.cy };
  let entered = false;
  for (let frame = 0; frame < 300; frame++) {
    const now = frame * 33;
    const noisy = { x: park.x + (random() - 0.5) * 0.01, y: park.y + (random() - 0.5) * 0.01 };
    if (engine.update("right", noisy, now).some((e) => e.type === "ENTER")) entered = true;
  }
  assert.equal(entered, false);
});

test("a deliberate pinch still registers through the same jitter", () => {
  const random = rng(99);
  const music = createHandMusicInstrument();
  let gated = false;
  for (let frame = 0; frame < 30; frame++) {
    const noisy = noisyHand(hand(0.2), random, 0.005);
    if (music.update({ right: noisy, now: frame * 33 }).params.gate === 1) gated = true;
  }
  assert.equal(gated, true);
});
