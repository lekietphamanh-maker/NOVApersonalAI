// Creative mode camera: ask for the webcam, retry one that is briefly busy (Nova's gesture reader letting go of it,
// or another app), and say in plain words what went wrong. Plain steps the tests can run without a real camera.
// 720p at 30 fps: hand tracking needs a steady frame rate more than pixels, and some webcams only reach 1080p slowly.
export const CAMERA_CONSTRAINTS = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 }, facingMode: "user" };
export const CAMERA_TRIES = 6;
// A blocked or missing camera doesn't come back by retrying; a busy one usually frees within a couple of seconds.
const GIVE_UP = new Set(["NotAllowedError", "SecurityError", "NotFoundError"]);
export const cameraDelayMs = (attempt) => Math.min(2000, 600 * (attempt + 1));

// What happened, and the exact thing to check.
export function describeCameraError(error) {
  switch (error?.name) {
    case "NotAllowedError":
      return { title: "The camera is blocked for this page",
        detail: "The browser is stopping Nova from using the camera. Allow the camera for this page (the camera icon in the address bar, or Windows Settings > Privacy & security > Camera), then press Try camera again." };
    case "NotReadableError":
      return { title: "Another app is using the camera",
        detail: "The camera is busy: another app (Zoom, Teams, a browser tab) may be holding it. Close it and press Try camera again." };
    case "NotFoundError":
      return { title: "No camera found",
        detail: "This PC reports no camera at all. Check it is plugged in and switched on, and allowed in Windows Settings > Privacy & security > Camera." };
    case "SecurityError":
      return { title: "This page can't ask for the camera",
        detail: "Open Creative mode from inside Nova's own window, not from another browser, then press Try camera again." };
    default:
      return { title: "The camera didn't start",
        detail: "Something stopped the camera before it opened. Press Try camera again; if it keeps failing, close other apps using the camera and check Windows Settings > Privacy & security > Camera." };
  }
}

// `request` is navigator.mediaDevices.getUserMedia; `sleep` is injectable so tests run instantly.
// Returns { stream, width, height } once the video is playing; throws the last error otherwise.
export async function requestCamera(video, request, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))) {
  let lastError = new Error("Camera unavailable");
  for (let attempt = 0; attempt < CAMERA_TRIES; attempt++) {
    let stream = null;
    try {
      stream = await request({ video: CAMERA_CONSTRAINTS, audio: false });
      video.srcObject = stream;
      await video.play();
      return { stream, width: video.videoWidth, height: video.videoHeight };
    } catch (error) {
      stream?.getTracks?.().forEach((track) => track.stop());
      lastError = error;
      if (GIVE_UP.has(error?.name)) break;
      if (attempt + 1 < CAMERA_TRIES) await sleep(cameraDelayMs(attempt));
    }
  }
  throw lastError;
}
