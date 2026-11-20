// Run: node --test tests/creative_gestures.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import {
  angleDelta, createDwell, createHandFilter, createObjectTracker, iou, isPinching, pickNearest, ringPositions, rollAngle, smooth,
  twoHandChange, videoToScreen,
} from "../creative/gestures.js";

/** A flat hand: wrist at (0.5, 0.8), middle knuckle 0.2 above it, thumb and index tips `gap` apart. */
function hand(gap) {
  const points = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.6, z: 0 }));
  points[0] = { x: 0.5, y: 0.8, z: 0 };
  points[9] = { x: 0.5, y: 0.6, z: 0 };
  points[4] = { x: 0.5 - gap / 2, y: 0.5, z: 0 };
  points[8] = { x: 0.5 + gap / 2, y: 0.5, z: 0 };
  return points;
}

test("pinch has hysteresis so it doesn't flicker at the edge", () => {
  assert.equal(isPinching(hand(0.05), false), true);   // 0.25 of palm: closed
  assert.equal(isPinching(hand(0.08), false), false);  // 0.40: not yet closed
  assert.equal(isPinching(hand(0.08), true), true);    // 0.40: stays closed
  assert.equal(isPinching(hand(0.12), true), false);   // 0.60: opens
});

test("mirrored cover mapping puts the camera's left on the screen's right", () => {
  const video = { width: 1280, height: 720 };
  const view = { width: 1280, height: 720 };
  assert.deepEqual(videoToScreen({ x: 0, y: 0 }, video, view), { x: 1280, y: 0 });
  assert.deepEqual(videoToScreen({ x: 0.25, y: 0.5 }, video, view), { x: 960, y: 360 });
  // Taller window: the video is scaled up and cropped left and right.
  const tall = videoToScreen({ x: 0.5, y: 0.5 }, video, { width: 600, height: 720 });
  assert.deepEqual(tall, { x: 300, y: 360 });
});

test("nearest pick respects the radius", () => {
  const objects = [{ id: "a", x: 100, y: 100 }, { id: "b", x: 300, y: 100 }];
  assert.equal(pickNearest({ x: 280, y: 110 }, objects, 120).id, "b");
  assert.equal(pickNearest({ x: 700, y: 700 }, objects, 120), null);
});

test("two hands: spreading scales, turning rotates", () => {
  const change = twoHandChange({ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 0, y: 0 }, { x: 0, y: 200 });
  assert.equal(change.scale, 2);
  assert.ok(Math.abs(change.turn - Math.PI / 2) < 1e-9);
});

test("angles wrap across ±π and roll follows the knuckle line", () => {
  assert.ok(Math.abs(angleDelta(Math.PI - 0.1, -Math.PI + 0.1) - 0.2) < 1e-9);
  const knuckles = Array.from({ length: 21 }, () => ({ x: 0, y: 0 }));
  knuckles[5] = { x: 0, y: 0 };
  knuckles[17] = { x: 10, y: 10 };
  assert.ok(Math.abs(rollAngle(knuckles) - Math.PI / 4) < 1e-9);
});

test("smoothing moves halfway and copies on the first frame", () => {
  const first = smooth(null, [{ x: 0, y: 0, z: 0 }]);
  assert.deepEqual(first, [{ x: 0, y: 0, z: 0 }]);
  assert.deepEqual(smooth(first, [{ x: 1, y: 2, z: 4 }]), [{ x: 0.5, y: 1, z: 2 }]);
});

test("control ring starts at the top and goes clockwise", () => {
  const [top, right, bottom, left] = ringPositions({ x: 100, y: 100 }, 50, 4).map((p) => ({ x: Math.round(p.x), y: Math.round(p.y) }));
  assert.deepEqual([top, right, bottom, left], [{ x: 100, y: 50 }, { x: 150, y: 100 }, { x: 100, y: 150 }, { x: 50, y: 100 }]);
});

test("a control fires after the finger rests on it; volume repeats, play/pause doesn't", () => {
  const dwell = createDwell({ hold: 0.4, repeat: 0.25 });
  assert.equal(dwell.update("volume_up", 0, true).fire, null);
  assert.ok(Math.abs(dwell.update("volume_up", 0.2, true).progress - 0.5) < 1e-9);
  assert.equal(dwell.update("volume_up", 0.41, true).fire, "volume_up");
  assert.equal(dwell.update("volume_up", 0.5, true).fire, null);
  assert.equal(dwell.update("volume_up", 0.67, true).fire, "volume_up"); // held: repeats
  assert.equal(dwell.update(null, 0.7).fire, null);                      // finger left
  assert.equal(dwell.update("play_pause", 0.8).fire, null);
  assert.equal(dwell.update("play_pause", 1.25).fire, "play_pause");
  assert.equal(dwell.update("play_pause", 2.5).fire, null);              // no repeat
});

test("object tracker: steady name and box, ignores one-frame ghosts, survives a short miss", () => {
  const tracker = createObjectTracker({ keepFor: 0.5 });
  const cup = (x, label = "cup", score = 0.8) => ({ label, score, box: { x, y: 100, w: 100, h: 120 } });
  assert.deepEqual(tracker.update([cup(100)], 0), []);                                  // one frame: not shown yet
  const [seen] = tracker.update([cup(110), { label: "kite", score: 0.5, box: { x: 600, y: 0, w: 20, h: 20 } }], 0.1);
  assert.equal(seen.label, "cup");
  assert.equal(seen.box.x, 105);                                                        // smoothed halfway
  assert.equal(tracker.update([cup(112, "vase", 0.55)], 0.2)[0].label, "cup");           // one odd label doesn't flip it
  assert.equal(tracker.update([], 0.5).length, 1);                                      // hand covered it a moment
  assert.equal(tracker.update([], 0.9).length, 0);                                      // gone
  assert.equal(iou({ x: 0, y: 0, w: 10, h: 10 }, { x: 5, y: 0, w: 10, h: 10 }), 50 / 150);
});

test("the hand filter steadies a still hand and keeps up with a fast one", () => {
  const filter = createHandFilter();
  let shake = 0, raw = 0;
  for (let frame = 0; frame < 60; frame++) {  // a still hand, with the tracker's ±0.004 jitter, at 30 fps
    const jitter = frame % 2 ? 0.004 : -0.004;
    const [point] = filter([{ x: 0.5 + jitter, y: 0.5, z: 0 }], frame / 30);
    if (frame > 10) { shake += Math.abs(point.x - 0.5); raw += Math.abs(jitter); }
  }
  assert.ok(shake < raw * 0.4, `still hand: ${shake} vs raw ${raw}`);
  let point;
  for (let frame = 60; frame < 66; frame++) [point] = filter([{ x: 0.5 + (frame - 59) * 0.05, y: 0.5, z: 0 }], frame / 30);
  assert.ok(Math.abs(point.x - 0.8) < 0.03, `fast move lags only ${Math.abs(point.x - 0.8)}`);
  const [fresh] = filter([{ x: 0.1, y: 0.1, z: 0 }], 10);  // back after a gap: no slide from the old place
  assert.deepEqual(fresh, { x: 0.1, y: 0.1, z: 0 });
});
