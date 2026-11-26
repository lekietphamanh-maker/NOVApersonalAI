// Run: node --test tests/camera.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { CAMERA_CONSTRAINTS, CAMERA_TRIES, cameraDelayMs, describeCameraError, requestCamera } from "../creative/camera.js";

const error = (name) => Object.assign(new Error(name), { name });
const fakeVideo = () => ({ srcObject: null, videoWidth: 1280, videoHeight: 720, play: async () => {} });
const stream = (onStop = () => {}) => ({ getTracks: () => [{ stop: onStop }] });

test("asks for a smooth 720p picture from the front camera", () => {
  assert.deepEqual(CAMERA_CONSTRAINTS, { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 }, facingMode: "user" });
});

test("retry waits grow, then cap at two seconds", () => {
  assert.deepEqual([0, 1, 2, 3, 10].map(cameraDelayMs), [600, 1200, 1800, 2000, 2000]);
});

test("every failure names what happened and the exact thing to check", () => {
  assert.match(describeCameraError(error("NotAllowedError")).title, /blocked/i);
  assert.match(describeCameraError(error("NotReadableError")).detail, /Try camera again/);
  assert.match(describeCameraError(error("NotFoundError")).detail, /Privacy & security > Camera/);
  assert.match(describeCameraError(error("SecurityError")).detail, /Nova's own window/);
  assert.match(describeCameraError(error("SomethingElse")).title, /didn't start/);
});

test("a working camera starts on the first try and plays in the video", async () => {
  const video = fakeVideo(), seen = [], camera = stream();
  const got = await requestCamera(video, async (constraints) => { seen.push(constraints); return camera; }, async () => {});
  assert.deepEqual(got, { stream: camera, width: 1280, height: 720 });
  assert.deepEqual(seen, [{ video: CAMERA_CONSTRAINTS, audio: false }]);
  assert.equal(video.srcObject, camera);
});

test("a busy camera is retried with growing waits instead of failing once", async () => {
  const waits = [];
  let calls = 0;
  const got = await requestCamera(fakeVideo(), async () => {
    calls += 1;
    if (calls < 3) throw error("NotReadableError");
    return stream();
  }, async (ms) => { waits.push(ms); });
  assert.ok(got.stream);
  assert.equal(calls, 3);
  assert.deepEqual(waits, [600, 1200]);
});

test("a blocked or missing camera stops at once instead of retrying", async () => {
  for (const name of ["NotAllowedError", "NotFoundError", "SecurityError"]) {
    let calls = 0;
    await assert.rejects(requestCamera(fakeVideo(), async () => { calls += 1; throw error(name); }, async () => {}),
      (caught) => caught.name === name);
    assert.equal(calls, 1, name);
  }
});

test("a stream whose video will not play is stopped, so it doesn't hold the camera", async () => {
  let stopped = 0;
  const video = fakeVideo();
  video.play = async () => { throw error("NotAllowedError"); };
  await assert.rejects(requestCamera(video, async () => stream(() => { stopped += 1; }), async () => {}),
    (caught) => caught.name === "NotAllowedError");
  assert.equal(stopped, 1);
});

test("a camera that stays busy gives up after the tries run out", async () => {
  let calls = 0;
  const waits = [];
  await assert.rejects(
    requestCamera(fakeVideo(), async () => { calls += 1; throw error("NotReadableError"); }, async (ms) => { waits.push(ms); }),
    (caught) => caught.name === "NotReadableError");
  assert.equal(calls, CAMERA_TRIES);
  assert.equal(waits.length, CAMERA_TRIES - 1);
});
