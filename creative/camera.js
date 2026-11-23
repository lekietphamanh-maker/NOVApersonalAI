// Creative mode camera: how the page asks for the webcam, in plain steps the tests can run
// without a real camera. The picture ladder starts sharp (1080p) and steps down only when the
// camera cannot do it; a camera that is briefly busy (Nova's own gesture reader letting go, or
// another app) is retried instead of failing once and leaving a black screen.
export const CAMERA_LADDER = [
  { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: "user" },
  { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
  { facingMode: "user" },
  true,
];
export const CAMERA_TRIES = 6;
// A blocked camera never unblocks by retrying; a busy one usually frees within a couple of seconds.
export const CAMERA_STOP_ERRORS = new Set(["NotAllowedError", "SecurityError"]);
export function cameraDelayMs(attempt) {
  return Math.min(2000, 600 * (attempt + 1));
}

// Plain words for each way the camera can fail: what happened, and the exact thing to check.
export function describeCameraError(error) {
  switch (error?.name) {
    case "NotAllowedError":
      return { title: "The camera is blocked for this page",
        detail: "Edge is stopping Nova from using the camera. Click the camera icon in the address bar (or the lock icon next to it), set Camera to Allow, then press Try camera again." };
    case "NotReadableError":
      return { title: "Another app is using the camera",
        detail: "The camera is busy — Nova's gesture reader may still be letting go, or another app (Zoom, Teams, a browser tab) is holding it. Wait a moment and press Try camera again; close the other app if it keeps failing." };
    case "NotFoundError":
      return { title: "No camera found",
        detail: "This PC reports no camera at all. Check it is plugged in and switched on, and allowed in Windows Settings > Privacy & security > Camera." };
    case "OverconstrainedError":
      return { title: "This camera can't do that picture size",
        detail: "Nova asked for a sharper picture than this camera offers. Press Try camera again and it will step down to a size the camera can do." };
    case "SecurityError":
      return { title: "This page can't ask for the camera",
        detail: "Open Creative mode from inside Nova's own window, not from another browser, then press Try camera again." };
    default:
      return { title: "The camera didn't start",
        detail: "Something stopped the camera before it opened. Press Try camera again; if it keeps failing, close other apps using the camera and check Windows Settings > Privacy & security > Camera." };
  }
}

function stopStream(stream) {
  stream?.getTracks?.().forEach((track) => track.stop());
}

// Ask for the camera, stepping down the picture ladder and retrying a busy camera.
// `request` is navigator.mediaDevices.getUserMedia; `sleep` is injectable so tests run instantly.
// Returns { stream, width, height } once the video is playing; throws the last error otherwise.
export async function requestCamera(video, request, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) {
  let level = 0;
  let lastError = new Error("Camera unavailable");
  for (let attempt = 0; attempt < CAMERA_TRIES; attempt++) {
    const constraints = CAMERA_LADDER[Math.min(level, CAMERA_LADDER.length - 1)];
    let stream;
    try {
      stream = await request({ video: constraints, audio: false });
    } catch (error) {
      lastError = error;
      if (CAMERA_STOP_ERRORS.has(error?.name)) break;
      if (error?.name === "OverconstrainedError") level += 1;
      if (attempt + 1 < CAMERA_TRIES) await sleep(cameraDelayMs(attempt));
      continue;
    }
    try {
      video.srcObject = stream;
      await video.play();
      return { stream, width: video.videoWidth, height: video.videoHeight };
    } catch (error) {
      stopStream(stream);
      lastError = error;
      if (CAMERA_STOP_ERRORS.has(error?.name)) break;
      if (attempt + 1 < CAMERA_TRIES) await sleep(cameraDelayMs(attempt));
    }
  }
  throw lastError;
}
