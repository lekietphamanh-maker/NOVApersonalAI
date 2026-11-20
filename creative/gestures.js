// Pure hand-gesture math for creative mode. No DOM, no three.js, so it runs under `node --test`.
// Landmarks are MediaPipe's: 21 points per hand, x and y normalized to the camera frame.

export const HAND = { WRIST: 0, THUMB_TIP: 4, INDEX_MCP: 5, INDEX_TIP: 8, MIDDLE_MCP: 9, PINKY_MCP: 17 };

export const HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

// Pinch closes below PINCH_ON and opens above PINCH_OFF (hysteresis stops flicker at the edge).
const PINCH_ON = 0.35;
const PINCH_OFF = 0.5;

export const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Wrist to middle knuckle: grows as the hand comes closer to the camera. */
export const palmSize = (landmarks) => distance(landmarks[HAND.WRIST], landmarks[HAND.MIDDLE_MCP]);

export function isPinching(landmarks, wasPinching) {
  const gap = distance(landmarks[HAND.THUMB_TIP], landmarks[HAND.INDEX_TIP]) / palmSize(landmarks);
  return wasPinching ? gap < PINCH_OFF : gap < PINCH_ON;
}

/** ✌ peace sign: index and middle fingers up, ring and pinky folded (thumb free). Holding it takes a photo. */
export function isPeaceSign(landmarks) {
  const wrist = landmarks[HAND.WRIST];
  const reach = (tip, joint) => distance(wrist, landmarks[tip]) / Math.max(1e-6, distance(wrist, landmarks[joint]));
  const up = (tip, joint) => reach(tip, joint) > 1.25;
  const folded = (tip, joint) => reach(tip, joint) < 1.0;
  return up(8, 6) && up(12, 10) && folded(16, 14) && folded(20, 18)
    && distance(landmarks[HAND.THUMB_TIP], landmarks[HAND.INDEX_TIP]) / palmSize(landmarks) > PINCH_OFF; // not a pinch
}

export function pinchPoint(landmarks) {
  const thumb = landmarks[HAND.THUMB_TIP];
  const index = landmarks[HAND.INDEX_TIP];
  return { x: (thumb.x + index.x) / 2, y: (thumb.y + index.y) / 2 };
}

/** Angle of the knuckle line, in screen space (y down). Twisting the wrist changes it. */
export function rollAngle(screenLandmarks) {
  const index = screenLandmarks[HAND.INDEX_MCP];
  const pinky = screenLandmarks[HAND.PINKY_MCP];
  return Math.atan2(pinky.y - index.y, pinky.x - index.x);
}

/** Smallest signed difference between two angles, so a turn across ±π doesn't jump. */
export function angleDelta(from, to) {
  return Math.atan2(Math.sin(to - from), Math.cos(to - from));
}

/**
 * Camera-normalized point -> screen pixels, for a video shown mirrored with `object-fit: cover`.
 * Mirroring is what makes the view behave like a mirror: your right hand appears on the right.
 */
export function videoToScreen(point, video, view) {
  const scale = Math.max(view.width / video.width, view.height / video.height);
  const shownWidth = video.width * scale;
  const shownHeight = video.height * scale;
  return {
    x: (view.width - shownWidth) / 2 + (1 - point.x) * shownWidth,
    y: (view.height - shownHeight) / 2 + point.y * shownHeight,
  };
}

/** The candidate nearest to `point` within `maxDistance` pixels, or null. Candidates: {id, x, y}. */
export function pickNearest(point, candidates, maxDistance) {
  let best = null;
  let bestDistance = maxDistance;
  for (const candidate of candidates) {
    const gap = distance(point, candidate);
    if (gap <= bestDistance) {
      best = candidate;
      bestDistance = gap;
    }
  }
  return best;
}

/** Two pinching hands: how much the gap between them grew, and how far the line between them turned. */
export function twoHandChange(startA, startB, nowA, nowB) {
  const startGap = Math.max(distance(startA, startB), 1);
  return {
    scale: distance(nowA, nowB) / startGap,
    turn: angleDelta(Math.atan2(startB.y - startA.y, startB.x - startA.x), Math.atan2(nowB.y - nowA.y, nowB.x - nowA.x)),
  };
}

/** Exponential smoothing per landmark; removes webcam jitter while keeping motion responsive. */
// The One Euro filter (Casiez, Roussel and Vogel, 2012) for the hand points: it smooths hard while the hand is still
// (no jitter) and hardly at all while it moves fast (no lag), which a fixed blend can't do both of. One filter per hand;
// times in seconds, cutoffs in Hz, positions in MediaPipe's 0..1 frame units.
export function createHandFilter({ minCutoff = 1.5, beta = 10, derivativeCutoff = 1 } = {}) {
  let last = null, speeds = null, lastTime = 0;
  const alpha = (cutoff, dt) => 1 / (1 + 1 / (2 * Math.PI * cutoff * dt));
  return (landmarks, time) => {
    if (!last || last.length !== landmarks.length || time - lastTime > 0.5) { // a new hand, or back after a gap
      last = landmarks.map((p) => ({ x: p.x, y: p.y, z: p.z ?? 0 }));
      speeds = landmarks.map(() => ({ x: 0, y: 0, z: 0 }));
      lastTime = time;
      return last.map((p) => ({ ...p }));
    }
    const dt = Math.max(1 / 240, time - lastTime);
    lastTime = time;
    last = landmarks.map((p, i) => {
      const point = {};
      for (const axis of ["x", "y", "z"]) {
        const value = p[axis] ?? 0, previous = last[i][axis];
        speeds[i][axis] += alpha(derivativeCutoff, dt) * ((value - previous) / dt - speeds[i][axis]);
        point[axis] = previous + alpha(minCutoff + beta * Math.abs(speeds[i][axis]), dt) * (value - previous);
      }
      return point;
    });
    return last.map((p) => ({ ...p }));
  };
}

export function smooth(previous, next, amount = 0.5) {
  if (!previous || previous.length !== next.length) return next.map((p) => ({ ...p }));
  return next.map((p, i) => ({
    x: previous[i].x + (p.x - previous[i].x) * amount,
    y: previous[i].y + (p.y - previous[i].y) * amount,
    z: (previous[i].z ?? 0) + ((p.z ?? 0) - (previous[i].z ?? 0)) * amount,
  }));
}

// ---------- the control orb ----------

/** Where the controls sit around the orb: evenly on a ring, the first at the top, going clockwise. */
export function ringPositions(center, radius, count) {
  return Array.from({ length: count }, (_, index) => {
    const angle = -Math.PI / 2 + (index / count) * Math.PI * 2;
    return { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius };
  });
}

/**
 * Press a control by holding a fingertip on it for `hold` seconds (a tap in the air is too easy to miss or
 * to trigger by accident). Repeating controls (volume) fire again every `repeat` seconds while held.
 * update(id or null, now in seconds, repeats) -> { fire: id or null, progress: 0..1 }
 */
export function createDwell({ hold = 0.4, repeat = 0.25 } = {}) {
  let current = null, since = 0, firedAt = null;
  return {
    update(id, now, repeats = false) {
      if (id !== current) { current = id; since = now; firedAt = null; return { fire: null, progress: 0 }; }
      if (id === null) return { fire: null, progress: 0 };
      if (firedAt === null) {
        const progress = (now - since) / hold;
        if (progress < 1) return { fire: null, progress };
        firedAt = now;
        return { fire: id, progress: 1 };
      }
      if (repeats && now - firedAt >= repeat) { firedAt = now; return { fire: id, progress: 1 }; }
      return { fire: null, progress: 1 };
    },
  };
}

// ---------- objects you show the camera ----------

/** Overlap of two boxes {x, y, w, h}: 0 apart, 1 identical. */
export function iou(a, b) {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  if (w <= 0 || h <= 0) return 0;
  const shared = w * h;
  return shared / (a.w * a.h + b.w * b.h - shared);
}

/**
 * Steadier object tracking than raw detections: each detection is matched to the track it overlaps most,
 * its box is smoothed, its name is a vote over recent frames (so "cup" doesn't flicker to "vase"), a track
 * survives short misses (an object turned or half covered by the hand), and one-frame ghosts are never shown.
 * update([{label, score, box}], now in seconds) -> [{id, label, score, box, age}]
 */
export function createObjectTracker({ smoothing = 0.5, keepFor = 0.7, minHits = 2, minOverlap = 0.2 } = {}) {
  let tracks = [], nextId = 1;
  return {
    update(detections, now) {
      const free = new Set(tracks);
      for (const detection of [...detections].sort((a, b) => b.score - a.score)) {
        let best = null, bestOverlap = minOverlap;
        for (const track of free) {
          const overlap = iou(track.box, detection.box);
          if (overlap >= bestOverlap) { best = track; bestOverlap = overlap; }
        }
        if (best) {
          free.delete(best);
          for (const key of ["x", "y", "w", "h"]) best.box[key] += (detection.box[key] - best.box[key]) * smoothing;
          for (const label in best.votes) best.votes[label] *= 0.85;
          best.votes[detection.label] = (best.votes[detection.label] || 0) + detection.score;
          best.score += (detection.score - best.score) * 0.3;
          best.seen = now;
          best.hits++;
        } else {
          tracks.push({ id: nextId++, box: { ...detection.box }, votes: { [detection.label]: detection.score }, score: detection.score,
            seen: now, born: now, hits: 1 });
        }
      }
      tracks = tracks.filter((track) => now - track.seen <= keepFor);
      return tracks.filter((track) => track.hits >= minHits).map((track) => ({
        id: track.id, box: { ...track.box }, score: track.score, age: now - track.born,
        label: Object.entries(track.votes).sort((a, b) => b[1] - a[1])[0][0],
      }));
    },
  };
}
