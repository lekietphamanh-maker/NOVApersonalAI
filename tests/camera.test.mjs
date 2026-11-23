// Run: node --test tests/camera.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import {
  CAMERA_LADDER, CAMERA_TRIES, CAMERA_WAIT_MS, cameraDelayMs, cameraTimeoutError, describeCameraError,
  requestCamera, requestWithTimeout,
} from "../creative/camera.js";

function error(name) {
  return Object.assign(new Error(name), { name });
}

function fakeVideo(width = 1920, height = 1080) {
  return { srcObject: null, videoWidth: width, videoHeight: height, play: async () => {} };
}

test("the picture ladder starts sharp and steps down only when the camera cannot do it", () => {
  assert.equal(CAMERA_LADDER[0].width.ideal, 1920);
  assert.equal(CAMERA_LADDER[0].height.ideal, 1080);
  assert.equal(CAMERA_LADDER[1].width.ideal, 1280);
  assert.equal(CAMERA_LADDER[1].height.ideal, 720);
  assert.deepEqual(CAMERA_LADDER[2], { facingMode: "user" });
  assert.equal(CAMERA_LADDER[3], true);
});

test("retry waits grow, then cap at two seconds", () => {
  assert.deepEqual([0, 1, 2, 3, 10].map(cameraDelayMs), [600, 1200, 1800, 2000, 2000]);
});

test("every failure names what happened and the exact thing to check", () => {
  const blocked = describeCameraError(error("NotAllowedError"));
  assert.match(blocked.title, /blocked/i);
  assert.match(blocked.detail, /Allow/i);
  const busy = describeCameraError(error("NotReadableError"));
  assert.match(busy.title, /using the camera/i);
  assert.match(busy.detail, /Try camera again/i);
  const missing = describeCameraError(error("NotFoundError"));
  assert.match(missing.detail, /Privacy & security > Camera/);
  const size = describeCameraError(error("OverconstrainedError"));
  assert.match(size.detail, /step down/i);
  const insecure = describeCameraError(error("SecurityError"));
  assert.match(insecure.detail, /Nova's own window/);
  const waiting = describeCameraError(error("CameraTimeoutError"));
  assert.match(waiting.title, /waiting for camera permission/i);
  assert.match(waiting.detail, /click Allow/i);
  assert.match(waiting.detail, /Try camera again/i);
  const unknown = describeCameraError(error("SomethingElse"));
  assert.match(unknown.title, /didn't start/);
});

test("a working camera is used at the sharpest size on the first try", async () => {
  const video = fakeVideo();
  const seen = [];
  const stream = { getTracks: () => [] };
  const got = await requestCamera(video, async (constraints) => { seen.push(constraints); return stream; }, async () => {});
  assert.equal(got.stream, stream);
  assert.equal(got.width, 1920);
  assert.equal(got.height, 1080);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].video, CAMERA_LADDER[0]);
  assert.equal(video.srcObject, stream);
});

test("a busy camera is retried with growing waits instead of failing once", async () => {
  const video = fakeVideo();
  const waits = [];
  let calls = 0;
  const stream = { getTracks: () => [] };
  const got = await requestCamera(video, async () => {
    calls += 1;
    if (calls < 3) throw error("NotReadableError");
    return stream;
  }, async (ms) => { waits.push(ms); });
  assert.equal(got.stream, stream);
  assert.equal(calls, 3);
  assert.deepEqual(waits, [600, 1200]);
});

test("a blocked camera stops at once instead of retrying", async () => {
  const video = fakeVideo();
  let calls = 0;
  await assert.rejects(
    requestCamera(video, async () => { calls += 1; throw error("NotAllowedError"); }, async () => {}),
    (caught) => caught.name === "NotAllowedError");
  assert.equal(calls, 1);
});

test("a camera that cannot do 1080p drops to 720p", async () => {
  const video = fakeVideo(1280, 720);
  const seen = [];
  const stream = { getTracks: () => [] };
  const got = await requestCamera(video, async (constraints) => {
    seen.push(constraints);
    if (seen.length === 1) throw error("OverconstrainedError");
    return stream;
  }, async () => {});
  assert.equal(got.width, 1280);
  assert.equal(seen.length, 2);
  assert.equal(seen[1].video, CAMERA_LADDER[1]);
});

test("a stream whose video will not play is stopped before retrying", async () => {
  let stopped = 0;
  const stream = { getTracks: () => [{ stop: () => { stopped += 1; } }] };
  const video = fakeVideo();
  let plays = 0;
  video.play = async () => { plays += 1; if (plays === 1) throw error("NotAllowedError"); };
  await assert.rejects(
    requestCamera(video, async () => stream, async () => {}),
    (caught) => caught.name === "NotAllowedError");
  assert.equal(stopped, 1);
  assert.equal(plays, 1);
});

test("a camera request that never answers fails after the wait instead of hanging", async () => {
  const video = fakeVideo();
  await assert.rejects(
    requestCamera(video, () => new Promise(() => {}), async () => {}, 30),
    (caught) => caught.name === "CameraTimeoutError");
});

test("a timed-out request stops at once instead of retrying for a minute", async () => {
  const video = fakeVideo();
  let calls = 0;
  await assert.rejects(
    requestCamera(video, () => { calls += 1; return new Promise(() => {}); }, async () => {}, 30),
    (caught) => caught.name === "CameraTimeoutError");
  assert.equal(calls, 1);
});

test("a late answer's stream is stopped instead of holding the camera", async () => {
  let stopped = 0;
  const stream = { getTracks: () => [{ stop: () => { stopped += 1; } }] };
  const video = fakeVideo();
  await assert.rejects(
    requestCamera(video, () => new Promise((resolve) => setTimeout(() => resolve(stream), 100)), async () => {}, 20),
    (caught) => caught.name === "CameraTimeoutError");
  await new Promise((resolve) => setTimeout(resolve, 150));
  assert.equal(stopped, 1);
});

test("requestWithTimeout passes a fast answer through and keeps its error", async () => {
  assert.equal(await requestWithTimeout(async () => "ok", 50), "ok");
  await assert.rejects(requestWithTimeout(async () => { throw error("NotFoundError"); }, 50),
    (caught) => caught.name === "NotFoundError");
  assert.equal(cameraTimeoutError().name, "CameraTimeoutError");
  assert.equal(CAMERA_WAIT_MS, 10_000);
});

test("a camera that stays busy gives up after the tries run out", async () => {
  const video = fakeVideo();
  let calls = 0;
  const waits = [];
  await assert.rejects(
    requestCamera(video, async () => { calls += 1; throw error("NotReadableError"); }, async (ms) => { waits.push(ms); }),
    (caught) => caught.name === "NotReadableError");
  assert.equal(calls, CAMERA_TRIES);
  assert.equal(waits.length, CAMERA_TRIES - 1);
});
