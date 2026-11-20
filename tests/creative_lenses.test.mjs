// Run: node --test tests/creative_lenses.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { LENSES, asciiRamp, charFor, createKissCam, glitchAmount, motionLevel, pixelBlockSize } from "../creative/lenses.js";
import { isPeaceSign } from "../creative/gestures.js";

test("pixels sharpen as your face comes closer", () => {
  assert.equal(pixelBlockSize(0), 28);                         // nobody there: chunky
  assert.ok(pixelBlockSize(0.1) > pixelBlockSize(0.25));      // closer face, smaller blocks
  assert.equal(pixelBlockSize(0.6), 3);                        // right up close: almost clear
});

test("the ASCII lens writes with your name's letters, least ink first", () => {
  const ink = { S: 30, A: 25, M: 40, N: 32, O: 28, V: 20 };
  assert.equal(asciiRamp("Sam", (char) => ink[char]), " ASM");
  assert.equal(asciiRamp("nova", (char) => ink[char]), " VAON");
  assert.equal(asciiRamp("Al", () => 1), " .:-=+*#%@");       // too few letters: the usual ramp
  assert.equal(charFor(" ASM", 0), " ");
  assert.equal(charFor(" ASM", 0.99), "M");
  assert.equal(charFor(" ASM", 1), "M");
});

test("glitch follows motion: still is clean", () => {
  const still = new Uint8ClampedArray(32 * 18 * 4).fill(120);
  const moved = still.map((value, index) => (index % 4 === 3 ? 255 : value + (index % 8 < 4 ? 60 : -60)));
  assert.equal(motionLevel(still, still), 0);
  assert.ok(motionLevel(still, moved) > 0.2);
  assert.equal(glitchAmount(0.005), 0);
  assert.equal(glitchAmount(0.5), 1);
  assert.ok(glitchAmount(0.05) > 0 && glitchAmount(0.05) < 1);
});

test("kiss cam: two faces held for 3 seconds take one photo, then it rests", () => {
  const kiss = createKissCam({ hold: 3, cooldown: 8 });
  assert.equal(kiss.update(1, 0).hearts, false);
  assert.equal(kiss.update(2, 1).shoot, false);
  assert.equal(kiss.update(2, 2.5).progress, 0.5);
  assert.equal(kiss.update(1, 3).progress, 0);   // one of you left: start over
  assert.equal(kiss.update(2, 4).shoot, false);
  assert.equal(kiss.update(2, 7).shoot, true);   // 3 seconds together
  assert.equal(kiss.update(2, 8).shoot, false);  // resting
  assert.equal(kiss.update(2, 14.9).shoot, false);
  assert.equal(kiss.update(2, 16).shoot, false); // a new hold starts after the rest
  assert.equal(kiss.update(2, 19).shoot, true);
  assert.deepEqual(LENSES, ["normal", "pixel", "ascii", "glitch", "slitscan", "echo"]);
});

/** A hand pointing up: wrist at the bottom, each finger's joint 0.1 above the wrist line and its tip `up` or curled. */
function hand({ index = true, middle = true, ring = false, pinky = false, thumbGap = 0.2 } = {}) {
  const points = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  points[0] = { x: 0.5, y: 0.9, z: 0 };
  points[9] = { x: 0.5, y: 0.7, z: 0 }; // middle knuckle: palm size 0.2
  const finger = (x, pip, tip, extended) => {
    points[pip] = { x, y: 0.62, z: 0 };
    points[tip] = { x, y: extended ? 0.45 : 0.72, z: 0 };
  };
  finger(0.44, 6, 8, index);
  finger(0.5, 10, 12, middle);
  finger(0.56, 14, 16, ring);
  finger(0.62, 18, 20, pinky);
  points[4] = { x: points[8].x - thumbGap, y: points[8].y, z: 0 };
  return points;
}

test("a peace sign takes a photo; a fist, an open hand or a pinch don't", () => {
  assert.equal(isPeaceSign(hand()), true);
  assert.equal(isPeaceSign(hand({ ring: true, pinky: true })), false);            // open hand
  assert.equal(isPeaceSign(hand({ index: false, middle: false })), false);        // fist
  assert.equal(isPeaceSign(hand({ middle: false })), false);                      // pointing
  assert.equal(isPeaceSign(hand({ thumbGap: 0.02 })), false);                     // pinching
});
