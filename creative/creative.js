// Creative mode: a mirrored webcam view with 3D holograms you move with your hands.
// Everything runs in this page: the camera picture is processed locally by MediaPipe and never uploaded.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { FaceLandmarker, FilesetResolver, HandLandmarker, ObjectDetector } from "./vendor/mediapipe/vision_bundle.mjs";
import {
  HAND_CONNECTIONS, angleDelta, createDwell, createHandFilter, createObjectTracker, isPeaceSign, isPinching, palmSize, pickNearest, pinchPoint,
  ringPositions, rollAngle, smooth, twoHandChange, videoToScreen,
} from "./gestures.js";
import { LENSES, LENS_NAMES, createKissCam, createLensRenderer } from "./lenses.js";
import { VOICES, createHandMusicInstrument, createZoneEngine } from "./handmusic.js";
import { HandMusicSynth } from "./handmusic-audio.js";

// Holograms take Nova's color, passed as #accent=r, g, b; gold by default.
const ACCENT_RGB = (() => {
  const value = new URLSearchParams(location.hash.slice(1)).get("accent");
  return value && /^\d{1,3}, \d{1,3}, \d{1,3}$/.test(value) ? value : "255, 176, 64";
})();
const CYAN = ACCENT_RGB.split(", ").reduce((hex, part) => hex * 256 + Number(part), 0);
const LIGHT = 0xffe2a8;
const NOSE_TIP = 1;
const video = document.getElementById("camera");
const hud = document.getElementById("hud");
const hudContext = hud.getContext("2d");
const statusLine = document.getElementById("status");
const trash = document.getElementById("trash");
const lensCanvas = document.getElementById("lens");
const view = { width: innerWidth, height: innerHeight };

// ---------- 3D scene ----------
const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("scene"), alpha: true, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
camera.position.set(0, 0, 8);
scene.add(new THREE.AmbientLight(0x88ccff, 0.7));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.6);
keyLight.position.set(3, 4, 6);
scene.add(keyLight);
const rimLight = new THREE.PointLight(CYAN, 40, 30);
rimLight.position.set(-4, 2, 3);
scene.add(rimLight);

const objects = []; // top-level groups the user can grab
let focus = null;   // the object last touched; explode acts on it

// Two looks: "wire" (glowing edges over faint faces with scan lines, the default) and "solid" (lit, glassy surfaces).
const STYLES = ["wire", "solid"];
let style = (() => { try { return STYLES.includes(localStorage.getItem("nova-holo-style")) ? localStorage.getItem("nova-holo-style") : "wire"; } catch { return "wire"; } })();
const holoTime = { value: 0 };
const EDGE_ANGLE = 26; // degrees: only real creases become lines, not every triangle

function solidMaterial(color = CYAN) {
  return new THREE.MeshStandardMaterial({
    color, emissive: color, emissiveIntensity: 0.28, metalness: 0.35, roughness: 0.3, transparent: true, opacity: 0.85,
  });
}

// Faint faces with horizontal scan lines drifting upward, added to three's own basic material.
function wireMaterial(color = CYAN) {
  const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.1, depthWrite: false,
    side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.holoTime = holoTime;
    shader.vertexShader = shader.vertexShader.replace("#include <common>", "#include <common>\nvarying float vHoloY;")
      .replace("#include <project_vertex>", "#include <project_vertex>\nvHoloY = (modelMatrix * vec4(transformed, 1.0)).y;");
    shader.fragmentShader = shader.fragmentShader.replace("#include <common>", "#include <common>\nvarying float vHoloY;\nuniform float holoTime;")
      .replace("#include <dithering_fragment>", "#include <dithering_fragment>\n"
        + "float scan = 0.55 + 0.45 * step(0.82, fract(vHoloY * 9.0 - holoTime * 0.6));\n"
        + "gl_FragColor.a *= scan;");
  };
  return material;
}

function hologramMaterial(color = CYAN) {
  return style === "wire" ? wireMaterial(color) : solidMaterial(color);
}

function edgeMaterial() {
  return new THREE.LineBasicMaterial({ color: style === "wire" ? CYAN : 0xbff8ff, transparent: true,
    opacity: style === "wire" ? 0.95 : 0.75, blending: style === "wire" ? THREE.AdditiveBlending : THREE.NormalBlending });
}

function edgeLines(geometry) {
  return new THREE.LineSegments(new THREE.EdgesGeometry(geometry, EDGE_ANGLE), edgeMaterial());
}

function hologramMesh(geometry, color) {
  const mesh = new THREE.Mesh(geometry, hologramMaterial(color));
  mesh.userData.holoColor = color ?? CYAN;
  mesh.add(edgeLines(geometry));
  return mesh;
}

/** Every hologram (and loaded model) in the current look; a model's own materials come back in "solid". */
function applyStyle(next) {
  style = STYLES.includes(next) ? next : style === "wire" ? "solid" : "wire";
  try { localStorage.setItem("nova-holo-style", style); } catch { /* private window: the look just isn't remembered */ }
  document.getElementById("scene").classList.toggle("glow", style === "wire");
  const button = document.getElementById("style");
  if (button) button.textContent = style === "wire" ? "Look: Wireframe" : "Look: Solid";
  for (const object of objects) {
    object.traverse((node) => {
      if (!node.isMesh) return;
      node.userData.ownMaterial ??= node.userData.holoColor === undefined ? node.material : null;
      const own = node.userData.ownMaterial;
      node.material = style === "solid" && own ? own : hologramMaterial(node.userData.holoColor ?? CYAN);
      let lines = node.children.find((child) => child.isLineSegments);
      if (!lines && style === "wire") { lines = edgeLines(node.geometry); node.add(lines); }
      if (lines) {
        lines.visible = style === "wire" || node.userData.holoColor !== undefined;
        lines.material = edgeMaterial();
      }
    });
  }
}

const SHAPES = {
  cube: () => new THREE.BoxGeometry(1.4, 1.4, 1.4),
  sphere: () => new THREE.IcosahedronGeometry(0.95, 3),
  torus: () => new THREE.TorusKnotGeometry(0.7, 0.22, 160, 24),
  cone: () => new THREE.ConeGeometry(0.8, 1.6, 48),
  cylinder: () => new THREE.CylinderGeometry(0.7, 0.7, 1.5, 48),
};

/** A part-based model, so "explode" has something to take apart. */
function buildReactor() {
  const group = new THREE.Group();
  group.add(hologramMesh(new THREE.CylinderGeometry(0.35, 0.35, 0.3, 40).rotateX(Math.PI / 2), 0xe8ffff));
  group.add(hologramMesh(new THREE.TorusGeometry(0.72, 0.08, 16, 64)));
  group.add(hologramMesh(new THREE.TorusGeometry(1.2, 0.12, 16, 80), 0x2aa8c4));
  for (let index = 0; index < 10; index++) {
    const angle = (index / 10) * Math.PI * 2;
    const segment = hologramMesh(new THREE.BoxGeometry(0.22, 0.3, 0.16), LIGHT);
    segment.position.set(Math.cos(angle) * 0.96, Math.sin(angle) * 0.96, 0);
    segment.rotation.z = angle;
    group.add(segment);
  }
  return group;
}

function addShape(kind) {
  if (kind === "reactor") return addObject(buildReactor(), "reactor");
  const group = new THREE.Group();
  group.add(hologramMesh((SHAPES[kind] ?? SHAPES.cube)()));
  return addObject(group, SHAPES[kind] ? kind : "cube");
}

function addObject(group, name) {
  group.name = name;
  group.updateMatrixWorld(true);
  // Remember where each part sits, and which way it flies out when exploded.
  for (const part of group.children) {
    const center = new THREE.Box3().setFromObject(part).getCenter(new THREE.Vector3());
    part.userData.home = part.position.clone();
    part.userData.direction = center.lengthSq() > 1e-4 ? center.normalize() : new THREE.Vector3(0, 0, 1);
  }
  Object.assign(group.userData, { explode: 0, explodeTarget: 0, spin: 0 });
  group.position.set(((objects.length % 3) - 1) * 2.6, objects.length >= 3 ? -1.4 : 0.4, 0);
  scene.add(group);
  objects.push(group);
  focus = group;
  return group;
}

function removeObject(object) {
  scene.remove(object);
  objects.splice(objects.indexOf(object), 1);
  if (focus === object) focus = objects.at(-1) ?? null;
}

/** Center a loaded model, size it to about two units, and flatten its parts so explode works. */
function normalizeModel(root) {
  const holder = new THREE.Group();
  holder.add(root);
  holder.updateMatrixWorld(true);
  const sphere = new THREE.Box3().setFromObject(root).getBoundingSphere(new THREE.Sphere());
  const scale = 1.2 / Math.max(sphere.radius, 1e-6);
  root.scale.multiplyScalar(scale);
  root.position.sub(sphere.center.multiplyScalar(scale));
  holder.updateMatrixWorld(true);
  const meshes = [];
  root.traverse((node) => { if (node.isMesh) meshes.push(node); });
  // shortcut: re-parenting bakes transforms but breaks skinned animation; fine for static models.
  for (const mesh of meshes) holder.attach(mesh);
  holder.remove(root);
  return holder;
}

async function loadModelFile(file) {
  const name = file.name.toLowerCase();
  const url = URL.createObjectURL(file);
  setStatus(`Loading ${file.name}…`);
  try {
    let root;
    if (name.endsWith(".glb") || name.endsWith(".gltf")) root = (await new GLTFLoader().loadAsync(url)).scene;
    else if (name.endsWith(".obj")) root = await new OBJLoader().loadAsync(url);
    else if (name.endsWith(".stl")) root = hologramMesh(await new STLLoader().loadAsync(url));
    else throw new Error("use a .glb, .gltf, .obj or .stl file");
    addObject(normalizeModel(root), file.name);
    applyStyle(style); // a loaded model takes the current look too

    setStatus(`Loaded ${file.name}`);
  } catch (error) {
    // shortcut: a .gltf that references separate .bin/texture files cannot load from one dropped file; use .glb.
    setStatus(`Could not load ${file.name}: ${error.message}`);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function setExplode(object, exploded) {
  for (const target of object ? [object] : objects) target.userData.explodeTarget = exploded ? 1 : 0;
}

function updateObjects(dt) {
  for (const object of objects) {
    const data = object.userData;
    data.explode += (data.explodeTarget - data.explode) * Math.min(1, dt * 4);
    object.children.forEach((part, index) => {
      if (!part.userData.home) return;
      part.position.copy(part.userData.home).addScaledVector(part.userData.direction, data.explode * 1.3);
      part.position.z += data.explode * (index - object.children.length / 2) * 0.3; // layers apart in depth
    });
    object.rotation.y += data.spin * dt;
    data.spin *= Math.exp(-dt * 1.2);
  }
}

// ---------- screen <-> world ----------
function project(position) {
  const point = position.clone().project(camera);
  return { x: ((point.x + 1) / 2) * view.width, y: ((1 - point.y) / 2) * view.height };
}

function screenToWorld(point, depth) {
  const through = new THREE.Vector3((point.x / view.width) * 2 - 1, -(point.y / view.height) * 2 + 1, 0.5).unproject(camera);
  const direction = through.sub(camera.position).normalize();
  return camera.position.clone().addScaledVector(direction, (depth - camera.position.z) / direction.z);
}

const grabRadius = () => Math.max(140, view.height * 0.16);
const overTrash = (point) => {
  const box = trash.getBoundingClientRect();
  return point.x >= box.left && point.x <= box.right && point.y >= box.top && point.y <= box.bottom;
};

// ---------- grabbing: hands and the mouse share one code path ----------
// A "pointer" is {point, pinching, palm, roll, grab}. Hands come from MediaPipe; the mouse is one more.
const pointers = new Map();
const DOUBLE_PINCH_MS = 450;

function startGrab(pointer) {
  if (orb.open && Math.hypot(pointer.point.x - orb.x, pointer.point.y - orb.y) < orb.ring + orb.size) return;
  const candidates = objects.map((object) => ({ object, ...project(object.position) }));
  const hit = pickNearest(pointer.point, candidates, grabRadius());
  if (!hit) return;
  const object = hit.object;
  focus = object;
  object.userData.spin = 0;
  // Two quick pinches (or a double-click) on a hologram take it apart, or put it back together.
  const now = performance.now();
  if (now - (object.userData.lastPinch || 0) < DOUBLE_PINCH_MS) {
    setExplode(object, !object.userData.explodeTarget);
    object.userData.lastPinch = 0;
  } else {
    object.userData.lastPinch = now;
  }
  const partner = [...pointers.values()].find((other) => other !== pointer && other.grab?.object === object);
  if (partner) {
    object.userData.pair = { first: partner, second: pointer, startA: { ...partner.point }, startB: { ...pointer.point },
      scale: object.scale.x, rotationZ: object.rotation.z };
  }
  pointer.grab = { object, offset: { x: pointer.point.x - hit.x, y: pointer.point.y - hit.y },
    startPalm: pointer.palm, startZ: object.position.z, startRoll: pointer.roll, startRotationZ: object.rotation.z };
}

function endGrab(pointer) {
  const object = pointer.grab?.object;
  pointer.grab = null;
  if (!object) return;
  const pair = object.userData.pair;
  if (pair) {
    object.userData.pair = null;
    const remaining = pair.first === pointer ? pair.second : pair.first;
    if (remaining.grab) startGrab(remaining); // re-anchor so the object doesn't jump
  } else if (overTrash(pointer.point)) {
    removeObject(object);
  }
}

function applyGrabs() {
  for (const pointer of pointers.values()) {
    const grab = pointer.grab;
    if (!grab || !objects.includes(grab.object)) continue;
    const object = grab.object;
    const pair = object.userData.pair;
    if (pair) {
      if (pointer !== pair.first) continue;
      const change = twoHandChange(pair.startA, pair.startB, pair.first.point, pair.second.point);
      object.scale.setScalar(THREE.MathUtils.clamp(pair.scale * change.scale, 0.2, 6));
      object.rotation.z = pair.rotationZ - change.turn; // screen angles run clockwise, three.js counter-clockwise
      continue;
    }
    // A hand coming toward the camera looks bigger: bring the object forward with it.
    const depth = THREE.MathUtils.clamp(grab.startZ + (pointer.palm / grab.startPalm - 1) * 5, -5, 3.5);
    object.position.copy(screenToWorld({ x: pointer.point.x - grab.offset.x, y: pointer.point.y - grab.offset.y }, depth));
    object.rotation.z = grab.startRotationZ - angleDelta(grab.startRoll, pointer.roll);
  }
  trash.classList.toggle("armed", [...pointers.values()].some((p) => p.grab && !p.grab.object.userData.pair && overTrash(p.point)));
}

function swipeToSpin(pointer, dt) {
  // An open hand moving fast across an object spins it, the way you'd flick a globe.
  const tip = pointer.screen?.[8];
  if (!tip || pointer.pinching) return;
  if (pointer.lastTip && dt > 0) {
    const speed = (tip.x - pointer.lastTip.x) / dt;
    const hit = Math.abs(speed) > 1400 && pickNearest(tip, objects.map((object) => ({ object, ...project(object.position) })), grabRadius());
    if (hit) hit.object.userData.spin = THREE.MathUtils.clamp(speed * 0.004, -12, 12);
  }
  pointer.lastTip = { ...tip };
}

// ---------- mouse fallback ----------
const mouse = { point: { x: 0, y: 0 }, pinching: false, palm: 1, roll: 0, grab: null };
pointers.set("mouse", mouse);
renderer.domElement.addEventListener("pointerdown", (event) => {
  mouse.point = { x: event.clientX, y: event.clientY };
  if (clickOrb(mouse.point)) return;
  mouse.pinching = true;
  startGrab(mouse);
});
addEventListener("pointermove", (event) => { mouse.point = { x: event.clientX, y: event.clientY }; });
addEventListener("pointerup", () => { if (mouse.pinching) { mouse.pinching = false; endGrab(mouse); } });
renderer.domElement.addEventListener("wheel", (event) => {
  const target = mouse.grab?.object ?? focus;
  if (target) target.scale.setScalar(THREE.MathUtils.clamp(target.scale.x * Math.exp(-event.deltaY * 0.001), 0.2, 6));
}, { passive: true });

// ---------- tracking ----------
let handLandmarker = null;
let faceLandmarker = null;
let objectDetector = null;
let detectObjects = true;
const objectTracker = createObjectTracker();
let shownObjects = [];
let face = null;       // the nearest face, in screen points
let faces = [];        // every face (up to two), in screen points
let faceWidth = 0;     // the nearest face's width as a share of the screen: how close you are
let head = { x: 0, y: 0 };

async function createLandmarker(Task, options, cpuOnly = false) {
  const vision = await FilesetResolver.forVisionTasks("./vendor/mediapipe/wasm");
  if (cpuOnly) return Task.createFromOptions(vision, { ...options, baseOptions: { ...options.baseOptions, delegate: "CPU" } });
  try {
    return await Task.createFromOptions(vision, { ...options, baseOptions: { ...options.baseOptions, delegate: "GPU" } });
  } catch {
    return await Task.createFromOptions(vision, { ...options, baseOptions: { ...options.baseOptions, delegate: "CPU" } });
  }
}

async function startTracking() {
  setStatus("Starting camera…");
  try {
    video.srcObject = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" }, audio: false });
    await video.play();
  } catch (error) {
    setStatus(`Camera unavailable (${error.name}). Allow the camera for this page, or use the mouse.`);
    window.creative.trackingError = error.name;
    return;
  }
  setStatus("Loading hand and face tracking…");
  try {
    // A higher tracking bar than the default keeps landmarks steady; detection stays quick to find a hand.
    [handLandmarker, faceLandmarker] = await Promise.all([
      createLandmarker(HandLandmarker, { baseOptions: { modelAssetPath: "./vendor/models/hand_landmarker.task" }, runningMode: "VIDEO",
        numHands: 2, minHandDetectionConfidence: 0.5, minHandPresenceConfidence: 0.5, minTrackingConfidence: 0.6 }),
      createLandmarker(FaceLandmarker, { baseOptions: { modelAssetPath: "./vendor/models/face_landmarker.task" }, runningMode: "VIDEO", numFaces: 2 }),
    ]);
    // Objects you hold up (80 everyday kinds); people are left out, you're always in the picture.
    objectDetector = await createLandmarker(ObjectDetector, { baseOptions: { modelAssetPath: "./vendor/models/efficientdet_lite0.tflite" },
      runningMode: "VIDEO", scoreThreshold: 0.4, maxResults: 5, categoryDenylist: ["person"] }, true).catch(() => null);
    // CPU: on some GPUs the detector's GPU path silently finds nothing; it is small and runs every other frame.
    window.creative.tracking = true;
  } catch (error) {
    setStatus(`Tracking failed to load: ${error.message}. The mouse still works.`);
    window.creative.trackingError = String(error.message);
  }
}

let lastVideoTime = -1;
let frameCount = 0;

function track(now, dt) {
  if (!handLandmarker || video.readyState < 2 || video.currentTime === lastVideoTime) return;
  lastVideoTime = video.currentTime;
  const videoSize = { width: video.videoWidth, height: video.videoHeight };
  const result = handLandmarker.detectForVideo(video, now);
  const seen = new Set(["mouse"]);
  result.landmarks.forEach((raw, index) => {
    let key = result.handedness[index]?.[0]?.categoryName ?? `hand${index}`;
    if (seen.has(key)) key = `${key}${index}`; // both hands taken for the same side: still two hands
    seen.add(key);
    const pointer = pointers.get(key) ?? { pinching: false, grab: null, filter: createHandFilter() };
    pointer.landmarks = pointer.filter(raw, now / 1000);
    pointer.screen = pointer.landmarks.map((point) => videoToScreen(point, videoSize, view));
    pointer.point = videoToScreen(pinchPoint(pointer.landmarks), videoSize, view);
    pointer.palm = palmSize(pointer.landmarks);
    pointer.roll = rollAngle(pointer.screen);
    const wasPinching = pointer.pinching;
    pointer.pinching = isPinching(pointer.landmarks, wasPinching);
    pointers.set(key, pointer);
    // While Hand Music is on, a pinch plays notes instead of grabbing holograms.
    if (!handMusic.on) {
      if (pointer.pinching && !wasPinching) startGrab(pointer);
      if (!pointer.pinching && wasPinching) endGrab(pointer);
      swipeToSpin(pointer, dt);
    }
  });
  for (const [key, pointer] of pointers) {
    if (!seen.has(key)) { endGrab(pointer); pointers.delete(key); } // hand left the picture
  }
  if (objectDetector && detectObjects && frameCount % 2 === 1) trackObjects(now, videoSize);
  if (faceLandmarker && frameCount++ % 3 === 0) {
    const found = faceLandmarker.detectForVideo(video, now).faceLandmarks;
    const width = (points) => Math.max(...points.map((point) => point.x)) - Math.min(...points.map((point) => point.x));
    const nearest = [...found].sort((a, b) => width(b) - width(a))[0]; // with two faces, the closer one leads
    faces = found.map((points) => points.map((point) => videoToScreen(point, videoSize, view)));
    face = nearest ? nearest.map((point) => videoToScreen(point, videoSize, view)) : null;
    faceWidth = face ? width(face) / view.width : 0;
    if (nearest) {
      const nose = nearest[NOSE_TIP];
      head = { x: head.x + ((0.5 - nose.x) - head.x) * 0.3, y: head.y + ((nose.y - 0.5) - head.y) * 0.3 };
    }
  }
  watchPeaceSign(now);
}

// ---------- Hand Music: play music with your hands ----------
//
// The logic lives in handmusic.js (zones, gesture mapping) and handmusic-audio.js (the synth),
// both adapted from the patterns in ewanqian/performable-music's hand-osc-lab. The input here is
// Nova's own webcam tracking (MediaPipe, 21 landmarks), never the lab's headset input.
// Sound goes to the default output — the same speaker Nova's voice uses.
const handMusic = {
  on: false, synth: new HandMusicSynth(),
  zones: createZoneEngine(), instrument: createHandMusicInstrument(),
  volume: (() => { try { return Math.min(100, Math.max(0, Number(localStorage.getItem("nova-handmusic-volume")) || 50)); } catch { return 50; } })(),
  lastParams: null,
};

async function setHandMusic(on) {
  const button = document.getElementById("handmusic-button");
  const panel = document.getElementById("handmusic-panel");
  const stateLine = document.getElementById("handmusic-state");
  if (on === handMusic.on) return;
  if (on) {
    try {
      await handMusic.synth.start();
    } catch (error) {
      setStatus(`Hand Music: audio failed to start (${error.message}).`);
      return;
    }
    handMusic.synth.setVolume(handMusic.volume / 100);
    handMusic.zones.reset(); handMusic.instrument.reset();
    handMusic.on = true;
    button.classList.add("on"); panel.hidden = false;
    stateLine.textContent = "Listening — pinch to play";
    setStatus("Hand Music on: pinch to play a note, move your index fingertip into a glowing circle to ring it.");
  } else {
    handMusic.on = false;
    handMusic.synth.panic(); // stop everything now: no drone may survive the mode being off
    handMusic.zones.reset(); handMusic.instrument.reset();
    button.classList.remove("on"); panel.hidden = true;
    stateLine.textContent = "Off";
    setStatus("Hand Music off.");
  }
}

/** Feed the tracked hands into the music logic, once per frame. Called from frame(). */
function updateHandMusic(now) {
  if (!handMusic.on) return;
  const aspect = view.width / Math.max(1, view.height);
  let left = null, right = null;
  for (const [key, pointer] of pointers) {
    if (key === "mouse" || !pointer.landmarks || !pointer.screen) continue;
    if (key.startsWith("Left") && !left) left = pointer;
    else if (key.startsWith("Right") && !right) right = pointer;
    else if (!left) left = pointer;
    else if (!right) right = pointer;
  }
  const zoneEvents = [];
  for (const [pointer, side] of [[left, "left"], [right, "right"]]) {
    // A missing hand is fed as null on purpose: the zone engine needs the null to report
    // TRACKING_LOST after its loss window. Skipping the side would leave a zone the vanished
    // hand was inside stuck "inside" forever, with no EXIT ever firing.
    const tip = pointer?.screen?.[8];
    zoneEvents.push(...handMusic.zones.update(side,
      tip ? { x: tip.x / view.width, y: tip.y / view.height } : null, now, aspect));
  }
  const { params, events } = handMusic.instrument.update({ left: left?.landmarks ?? null, right: right?.landmarks ?? null, zoneEvents, now });
  handMusic.lastParams = params;
  let lost = false;
  for (const event of events) {
    if (event.type === "ZONE_ENTER") handMusic.synth.triggerZone(event.zone);
    else if (event.type === "ZONE_LOST") lost = true; // hand vanished: fade, never invent a note-off
  }
  if (lost || !left && !right) handMusic.synth.release();
  handMusic.synth.update(params, now);
  const stateLine = document.getElementById("handmusic-state");
  stateLine.textContent = params.gate ? `Playing · ${VOICES[params.timbre].name}` : `Listening · ${VOICES[params.timbre].name}`;
}

function drawHandMusicZones() {
  if (!handMusic.on) return;
  const aspect = view.width / Math.max(1, view.height);
  for (const zone of handMusic.zones.zones) {
    const cx = zone.cx * view.width, cy = zone.cy * view.height, r = zone.r * view.height;
    const inside = handMusic.zones.isInside("left", zone.id) || handMusic.zones.isInside("right", zone.id);
    hudContext.beginPath();
    hudContext.arc(cx, cy, r, 0, Math.PI * 2);
    hudContext.strokeStyle = inside ? `rgba(${ACCENT_RGB}, 0.95)` : `rgba(${ACCENT_RGB}, 0.45)`;
    hudContext.lineWidth = inside ? 3 : 1.5;
    hudContext.stroke();
    hudContext.fillStyle = inside ? `rgba(${ACCENT_RGB}, 0.18)` : `rgba(${ACCENT_RGB}, 0.05)`;
    hudContext.fill();
    hudContext.fillStyle = `rgba(${ACCENT_RGB}, 0.9)`;
    hudContext.font = "600 11px Segoe UI, system-ui, sans-serif";
    hudContext.textAlign = "center";
    hudContext.fillText(`${zone.id} · ${zone.name}`, cx, cy - r - 8);
    hudContext.textAlign = "left";
  }
  if (handMusic.lastParams) {
    const p = handMusic.lastParams;
    hudContext.fillStyle = `rgba(${ACCENT_RGB}, 0.85)`;
    hudContext.font = "600 11px Segoe UI, system-ui, sans-serif";
    hudContext.fillText(`cutoff ${(p.cutoff * 100) | 0}% · resonance ${(p.resonance * 100) | 0}% · spread ${(p.spread * 100) | 0}% · energy ${(p.energy * 100) | 0}%`,
      26, view.height - 48);
  }
}

function trackObjects(now, videoSize) {
  const detections = objectDetector.detectForVideo(video, now).detections.map((detection) => {
    const { originX, originY, width, height } = detection.boundingBox;
    const a = videoToScreen({ x: originX / videoSize.width, y: originY / videoSize.height }, videoSize, view);
    const b = videoToScreen({ x: (originX + width) / videoSize.width, y: (originY + height) / videoSize.height }, videoSize, view);
    const category = detection.categories[0];
    return { label: category.categoryName, score: category.score,
      box: { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) } };
  });
  shownObjects = objectTracker.update(detections, now / 1000);
}

/** An object is "held" when one of your hands is inside its box. */
function heldBy(box) {
  return [...pointers.entries()].some(([key, pointer]) => key !== "mouse" && pointer.screen
    && pointer.screen.some((point) => point.x > box.x && point.x < box.x + box.w && point.y > box.y && point.y < box.y + box.h));
}

let lastSeenReport = 0;
function reportSeen(now) {
  if (now - lastSeenReport < 1000) return;
  lastSeenReport = now;
  const names = shownObjects.map((item) => `${item.label}${heldBy(item.box) ? " (held)" : ""}`);
  fetch("/seen", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(names) }).catch(() => {});
}

// ---------- the control orb: touch it with a fingertip and controls open around it ----------
const CONTROLS = [
  { id: "volume_up", label: "VOL +", icon: "+", repeat: true },
  { id: "next", label: "NEXT", icon: "⏭" },
  { id: "play_pause", label: "PLAY / PAUSE", icon: "⏯" },
  { id: "exit", label: "EXIT", icon: "✕" },
  { id: "previous", label: "PREV", icon: "⏮" },
  { id: "volume_down", label: "VOL −", icon: "−", repeat: true },
  { id: "scan", label: "WHAT IS THIS", icon: "🔍" },
  { id: "photo", label: "PHOTO", icon: "📸" },
];
const orb = { x: 0, y: 0, size: 40, ring: 110, open: 0, openUntil: 0, hover: null, progress: 0, flash: null, flashAt: 0 };
const dwell = createDwell();

function layoutOrb() {
  // Bottom-left corner, above the status line, with room for the ring: the middle stays free for holograms.
  orb.size = Math.max(26, Math.min(44, Math.min(view.width, view.height) * 0.045));
  orb.ring = orb.size * 3.6; // eight controls need the room
  const reach = orb.ring + orb.size * 0.62 + 16;
  orb.x = 26 + reach;
  orb.y = view.height - 48 - reach;
  orb.buttons = ringPositions(orb, orb.ring, CONTROLS.length);
}

function fireControl(id) {
  orb.flash = id;
  orb.flashAt = performance.now();
  if (id === "exit") return exitCreative();
  if (id === "scan") return sendSnapshot(true);
  if (id === "photo") return startPhoto();
  fetch("/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: id }) }).catch(() => {});
}

// ---------- a photo of what you show, for Nova's vision model ----------
let scanLabel = null; // { text, box, at }: what the vision model said, shown next to the object

/** What you are showing: the object in your hand, else the biggest one, else around your hand, else the middle. */
function snapshotBox() {
  const held = shownObjects.find((item) => heldBy(item.box));
  const biggest = [...shownObjects].sort((a, b) => b.box.w * b.box.h - a.box.w * a.box.h)[0];
  const object = held ?? biggest;
  let box = object?.box;
  if (!box) {
    const hand = [...pointers.entries()].find(([key, pointer]) => key !== "mouse" && pointer.screen)?.[1];
    if (hand) {
      const xs = hand.screen.map((point) => point.x), ys = hand.screen.map((point) => point.y);
      const size = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.8;
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
      box = { x: cx - size / 2, y: cy - size / 2, w: size, h: size };
    } else {
      box = { x: view.width * 0.25, y: view.height * 0.2, w: view.width * 0.5, h: view.height * 0.6 };
    }
  }
  const pad = 0.15, x = Math.max(0, box.x - box.w * pad), y = Math.max(0, box.y - box.h * pad);
  return { guess: object?.label ?? "", box: { x, y, w: Math.min(view.width - x, box.w * (1 + 2 * pad)), h: Math.min(view.height - y, box.h * (1 + 2 * pad)) } };
}

function sendSnapshot(ask) {
  if (video.readyState < 2 || !video.videoWidth) return;
  const { box, guess } = snapshotBox();
  const scale = Math.min(1, 384 / Math.max(box.w, box.h)); // enough to name a thing; smaller is much faster
  const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(box.w * scale), height: Math.round(box.h * scale) });
  const context = canvas.getContext("2d");
  // The screen shows the camera mirrored; the photo is not, so writing on the object reads the right way round.
  const fit = Math.max(view.width / video.videoWidth, view.height / video.videoHeight);
  const shownWidth = video.videoWidth * fit, shownHeight = video.videoHeight * fit;
  const left = (view.width - shownWidth) / 2, top = (view.height - shownHeight) / 2;
  context.scale(scale, scale);
  context.translate(-(2 * left + shownWidth - box.x - box.w), -box.y);
  context.drawImage(video, left, top, shownWidth, shownHeight);
  if (ask) scanLabel = { text: "Looking…", box, at: performance.now() };
  fetch("/snapshot", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image: canvas.toDataURL("image/jpeg", 0.85), guess, ask }) }).catch(() => {});
}

function drawScanLabel(now) {
  if (!scanLabel || now - scanLabel.at > 12000) return;
  const { x, y, w, h } = scanLabel.box;
  hudContext.setLineDash([6, 6]);
  hudContext.strokeStyle = "rgba(255, 236, 200, 0.8)";
  hudContext.lineWidth = 1.5;
  hudContext.strokeRect(x, y, w, h);
  hudContext.setLineDash([]);
  const text = `🔍 ${scanLabel.text}`;
  hudContext.font = "600 15px Segoe UI, system-ui, sans-serif";
  hudContext.textAlign = "left";
  hudContext.textBaseline = "top";
  // Below the object, or above it when it reaches the bottom (the status line lives there).
  const width = hudContext.measureText(text).width + 20, labelY = y + h + 46 < view.height - 50 ? y + h + 8 : Math.max(60, y - 38);
  hudContext.fillStyle = "rgba(6, 9, 12, 0.85)";
  hudContext.fillRect(x, labelY, width, 30);
  hudContext.strokeStyle = `rgba(${ACCENT_RGB}, 0.9)`;
  hudContext.strokeRect(x, labelY, width, 30);
  hudContext.fillStyle = "#ffecc8";
  hudContext.fillText(text, x + 10, labelY + 7);
}

function exitCreative() {
  if (window.parent !== window) window.parent.postMessage("alfred:close-creative", "*");
  else {
    // Its own window: Nova closes it (a page can't always close the window it was opened in).
    fetch("/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "exit" }) })
      .catch(() => {}).finally(() => window.close());
  }
}

/** The mouse can use the orb too: click the orb to open it, click a control to press it. */
function clickOrb(point) {
  if (Math.hypot(point.x - orb.x, point.y - orb.y) < orb.size) { orb.openUntil = performance.now() + 4000; return true; }
  if (!orb.open) return false;
  const index = orb.buttons.findIndex((button) => Math.hypot(point.x - button.x, point.y - button.y) < orb.size * 0.8);
  if (index < 0) return false;
  fireControl(CONTROLS[index].id);
  orb.openUntil = performance.now() + 4000;
  return true;
}

function updateOrb(now, dt) {
  // Index fingertips of open (not pinching) hands are the "touch" points.
  const tips = [...pointers.entries()].filter(([key, pointer]) => key !== "mouse" && pointer.screen && !pointer.pinching)
    .map(([, pointer]) => pointer.screen[8]);
  const near = (point, radius) => Math.hypot(point.x - orb.x, point.y - orb.y) < radius;
  if (tips.some((tip) => near(tip, orb.size * 1.2))) orb.openUntil = now + 2500;
  if (orb.open > 0.5 && tips.some((tip) => near(tip, orb.ring + orb.size))) orb.openUntil = Math.max(orb.openUntil, now + 1500);
  const target = now < orb.openUntil ? 1 : 0;
  orb.open += (target - orb.open) * Math.min(1, dt * 9);
  let hovered = null;
  if (orb.open > 0.8) {
    for (const tip of tips) {
      const index = orb.buttons.findIndex((button) => Math.hypot(tip.x - button.x, tip.y - button.y) < orb.size * 0.85);
      if (index >= 0) { hovered = CONTROLS[index]; break; }
    }
  }
  const { fire, progress } = dwell.update(hovered?.id ?? null, now / 1000, hovered?.repeat);
  orb.hover = hovered?.id ?? null;
  orb.progress = progress;
  if (fire) fireControl(fire);
}

function drawOrb(now) {
  const t = now / 1000, open = orb.open;
  const glow = hudContext.createRadialGradient(orb.x, orb.y, 0, orb.x, orb.y, orb.size * 2.2);
  glow.addColorStop(0, `rgba(${ACCENT_RGB}, ${0.28 + open * 0.2})`);
  glow.addColorStop(1, `rgba(${ACCENT_RGB}, 0)`);
  hudContext.fillStyle = glow;
  hudContext.fillRect(orb.x - orb.size * 2.2, orb.y - orb.size * 2.2, orb.size * 4.4, orb.size * 4.4);
  hudContext.lineWidth = 2;
  hudContext.strokeStyle = `rgba(${ACCENT_RGB}, 0.9)`;
  hudContext.beginPath();
  hudContext.arc(orb.x, orb.y, orb.size * (0.92 + Math.sin(t * 2.2) * 0.04), 0, Math.PI * 2);
  hudContext.stroke();
  hudContext.lineWidth = 1.2;
  for (let index = 0; index < 3; index++) { // orbiting arcs
    hudContext.beginPath();
    hudContext.arc(orb.x, orb.y, orb.size * (0.55 + index * 0.14), t * (1.4 - index * 0.5) + index, t * (1.4 - index * 0.5) + index + 2.4);
    hudContext.strokeStyle = `rgba(${ACCENT_RGB}, ${0.5 - index * 0.12})`;
    hudContext.stroke();
  }
  hudContext.textAlign = "center";
  hudContext.textBaseline = "middle";
  hudContext.font = "600 9px JetBrains Mono, Consolas, monospace";
  hudContext.fillStyle = `rgba(255, 236, 200, ${0.75 - open * 0.5})`;
  hudContext.fillText("TOUCH", orb.x, orb.y);
  if (open < 0.02) return;
  hudContext.beginPath(); // the ring the controls sit on
  hudContext.arc(orb.x, orb.y, orb.ring * open, 0, Math.PI * 2);
  hudContext.strokeStyle = `rgba(${ACCENT_RGB}, ${0.25 * open})`;
  hudContext.stroke();
  CONTROLS.forEach((control, index) => {
    const spot = orb.buttons[index];
    const x = orb.x + (spot.x - orb.x) * open, y = orb.y + (spot.y - orb.y) * open, radius = orb.size * 0.62;
    const hot = orb.hover === control.id, flashing = orb.flash === control.id && now - orb.flashAt < 300;
    hudContext.beginPath();
    hudContext.arc(x, y, radius, 0, Math.PI * 2);
    hudContext.fillStyle = flashing ? `rgba(${ACCENT_RGB}, 0.85)` : hot ? `rgba(${ACCENT_RGB}, 0.3)` : "rgba(6, 9, 12, 0.72)";
    hudContext.fill();
    hudContext.lineWidth = hot ? 2 : 1.2;
    hudContext.strokeStyle = control.id === "exit" ? `rgba(255, 110, 130, ${open})` : `rgba(${ACCENT_RGB}, ${open})`;
    hudContext.stroke();
    if (hot && orb.progress < 1) { // fills while you hold your finger there
      hudContext.beginPath();
      hudContext.arc(x, y, radius + 5, -Math.PI / 2, -Math.PI / 2 + orb.progress * Math.PI * 2);
      hudContext.lineWidth = 3;
      hudContext.strokeStyle = "rgba(255, 236, 200, 0.95)";
      hudContext.stroke();
    }
    hudContext.fillStyle = flashing ? "#000" : `rgba(255, 244, 226, ${open})`;
    hudContext.font = `600 ${Math.round(radius * 0.8)}px Segoe UI Symbol, Segoe UI, sans-serif`;
    hudContext.fillText(control.icon, x, y + 1);
    hudContext.font = "600 8.5px JetBrains Mono, Consolas, monospace";
    hudContext.fillStyle = `rgba(${ACCENT_RGB}, ${open})`;
    hudContext.fillText(control.label, x, y + radius + 11);
  });
}

function drawObjects(now) {
  for (const item of shownObjects) {
    const { x, y, w, h } = item.box, held = heldBy(item.box), corner = Math.min(22, w / 4, h / 4);
    hudContext.strokeStyle = held ? "rgba(255, 236, 200, 0.95)" : `rgba(${ACCENT_RGB}, 0.85)`;
    hudContext.lineWidth = held ? 2.5 : 1.8;
    for (const [cx, cy, dx, dy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) {
      hudContext.beginPath();
      hudContext.moveTo(cx + dx * corner, cy);
      hudContext.lineTo(cx, cy);
      hudContext.lineTo(cx, cy + dy * corner);
      hudContext.stroke();
    }
    const scan = y + ((now / 1000 * 0.6 + item.id * 0.3) % 1) * h; // a scan line sweeping the object
    hudContext.fillStyle = `rgba(${ACCENT_RGB}, 0.18)`;
    hudContext.fillRect(x, scan, w, 2);
    const text = `${item.label.toUpperCase()} ${Math.round(item.score * 100)}%${held ? " · HELD" : ""}${item.age > 1.5 ? " · LOCKED" : ""}`;
    hudContext.font = "600 11px JetBrains Mono, Consolas, monospace";
    hudContext.textAlign = "left";
    hudContext.textBaseline = "bottom";
    const width = hudContext.measureText(text).width + 12;
    hudContext.fillStyle = "rgba(6, 9, 12, 0.75)";
    hudContext.fillRect(x, y - 20, width, 18);
    hudContext.fillStyle = held ? "#ffecc8" : `rgb(${ACCENT_RGB})`;
    hudContext.fillText(text, x + 6, y - 5);
  }
}

function updateParallax() {
  // Move the virtual camera with your head, so objects shift like real ones in front of you.
  camera.position.set(head.x * 4, -head.y * 3, 8);
  camera.lookAt(0, 0, 0);
}

// ---------- lenses, photo booth and kiss cam (camera ideas from github.com/tigrisli/curious-machines) ----------
const lensRenderer = createLensRenderer(lensCanvas, ACCENT_RGB);
lensRenderer.setName(new URLSearchParams(location.hash.slice(1)).get("name") ?? "");
let lens = "normal";
let kissCamOn = false;
const kissCam = createKissCam();
let kiss = { hearts: false, progress: 0 };
// A held ✌ is also what opens creative mode (webcam gestures): the photo sign only counts after a moment.
const photo = { countdownFrom: 0, flashAt: 0, saved: "", count: 0, peaceSince: 0, quietUntil: performance.now() + 6000 };
const flash = document.getElementById("flash");
const shot = document.getElementById("shot");
let shotTimer = 0;

function setLens(name) {
  if (!LENSES.includes(name)) return;
  lens = name;
  lensRenderer.reset();
  document.body.classList.toggle("lensed", lens !== "normal");
  const button = document.getElementById("lens-button");
  button.textContent = `Lens: ${LENS_NAMES[lens]}`;
  button.classList.toggle("on", lens !== "normal");
}

function setKissCam(on) {
  kissCamOn = on;
  document.getElementById("kisscam").classList.toggle("on", on);
}

/** 3-2-1, then the photo. Again while counting does nothing. */
function startPhoto() {
  if (!photo.countdownFrom) photo.countdownFrom = performance.now();
}

function updatePhoto(now) {
  if (!photo.countdownFrom || now - photo.countdownFrom < 3000) return;
  if (video.readyState < 2 || !video.videoWidth) {
    if (now - photo.countdownFrom > 12000) { photo.countdownFrom = 0; setStatus("No camera picture to take a photo of."); }
    return; // the camera is still starting: wait for it
  }
  photo.countdownFrom = 0;
  takePhoto();
}

/** What you see, without Nova's dimming and HUD: the lens or the plain mirror, with the holograms on top. */
function takePhoto() {
  const scale = Math.min(1, 1600 / Math.max(view.width, view.height));
  const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(view.width * scale), height: Math.round(view.height * scale) });
  const context = canvas.getContext("2d");
  if (lens !== "normal") {
    context.drawImage(lensCanvas, 0, 0, canvas.width, canvas.height);
  } else {
    const fit = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
    const width = video.videoWidth * fit, height = video.videoHeight * fit;
    context.setTransform(-1, 0, 0, 1, canvas.width, 0);
    context.drawImage(video, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
    context.setTransform(1, 0, 0, 1, 0, 0);
  }
  renderer.render(scene, camera); // in the same task, so the 3D canvas still holds this frame
  context.drawImage(renderer.domElement, 0, 0, canvas.width, canvas.height);
  context.font = `600 ${Math.round(12 * scale + 4)}px "JetBrains Mono", Consolas, monospace`;
  context.fillStyle = `rgba(${ACCENT_RGB}, 0.85)`;
  context.fillText(`NOVA · ${new Date().toLocaleString()}`, 14, canvas.height - 14);
  photo.flashAt = performance.now();
  flash.style.transition = "none";
  flash.style.opacity = "0.85";
  requestAnimationFrame(() => { flash.style.transition = "opacity 0.5s ease-out"; flash.style.opacity = "0"; });
  const image = canvas.toDataURL("image/jpeg", 0.92);
  showShot(image, "SAVING…");
  fetch("/photo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ image, lens }) })
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
    .then(({ saved }) => { photo.saved = saved; photo.count += 1; showShot(image, `Saved · Pictures\\Nova\\${saved}`); })
    .catch(() => showShot(image, "COULDN'T SAVE THE PHOTO"));
}

function showShot(image, caption) {
  shot.querySelector("img").src = image;
  shot.querySelector("span").textContent = caption;
  shot.classList.add("show");
  clearTimeout(shotTimer);
  shotTimer = setTimeout(() => shot.classList.remove("show"), 4500);
}

/** Hold up a peace sign for a moment: a photo (once per hold, then a short pause). */
function watchPeaceSign(now) {
  const peace = [...pointers.entries()].some(([key, pointer]) => key !== "mouse" && pointer.landmarks && !pointer.grab
    && isPeaceSign(pointer.landmarks));
  if (!peace || now < photo.quietUntil) { photo.peaceSince = 0; return; }
  photo.peaceSince ||= now;
  if (now - photo.peaceSince > 700) {
    photo.peaceSince = 0;
    photo.quietUntil = now + 6000;
    startPhoto();
  }
}

function updateKissCam(now) {
  if (!kissCamOn) { kiss = { hearts: false, progress: 0 }; return; }
  kiss = kissCam.update(faces.length, now / 1000);
  if (kiss.shoot) startPhoto();
}

function heartPath(x, y, size) {
  hudContext.beginPath();
  hudContext.moveTo(x, y + size * 0.35);
  hudContext.bezierCurveTo(x - size * 1.1, y - size * 0.35, x - size * 0.45, y - size * 1.05, x, y - size * 0.45);
  hudContext.bezierCurveTo(x + size * 0.45, y - size * 1.05, x + size * 1.1, y - size * 0.35, x, y + size * 0.35);
  hudContext.closePath();
}

function drawKissCam(now) {
  if (!kissCamOn) return;
  hudContext.font = `700 14px "Rajdhani", "Segoe UI", sans-serif`;
  hudContext.textAlign = "center";
  if (faces.length !== 2) {
    hudContext.fillStyle = "rgba(255, 140, 170, 0.9)";
    hudContext.fillText("KISS CAM · WAITING FOR TWO FACES", view.width / 2, 74);
    hudContext.textAlign = "start";
    return;
  }
  const [a, b] = faces.map((points) => points[NOSE_TIP]);
  const x = (a.x + b.x) / 2, y = Math.min(a.y, b.y) - Math.abs(a.x - b.x) * 0.15;
  const size = Math.max(26, Math.abs(a.x - b.x) * 0.22) * (1 + 0.08 * Math.sin(now / 160));
  heartPath(x, y, size);
  hudContext.fillStyle = "rgba(255, 70, 120, 0.75)";
  hudContext.fill();
  hudContext.lineWidth = 3;
  hudContext.strokeStyle = "rgba(255, 210, 225, 0.9)";
  hudContext.stroke();
  if (kiss.progress > 0 && !photo.countdownFrom) {
    hudContext.beginPath();
    hudContext.arc(x, y - size * 0.25, size * 1.35, -Math.PI / 2, -Math.PI / 2 + kiss.progress * Math.PI * 2);
    hudContext.stroke();
  }
  hudContext.fillStyle = "rgba(255, 210, 225, 0.95)";
  hudContext.fillText("KISS CAM", x, y - size * 1.6);
  hudContext.textAlign = "start";
}

function drawCountdown(now) {
  if (!photo.countdownFrom) return;
  const elapsed = (now - photo.countdownFrom) / 1000;
  const number = Math.max(1, 3 - Math.floor(elapsed));
  const x = view.width / 2, y = view.height / 2, radius = Math.min(view.width, view.height) * 0.12;
  hudContext.lineWidth = 6;
  hudContext.strokeStyle = `rgba(${ACCENT_RGB}, 0.9)`;
  hudContext.beginPath();
  hudContext.arc(x, y, radius, -Math.PI / 2, -Math.PI / 2 + (elapsed % 1) * Math.PI * 2);
  hudContext.stroke();
  hudContext.fillStyle = "#fff";
  hudContext.shadowColor = `rgb(${ACCENT_RGB})`;
  hudContext.shadowBlur = 24;
  hudContext.font = `700 ${Math.round(radius * 1.2)}px "Rajdhani", "Segoe UI", sans-serif`;
  hudContext.textAlign = "center";
  hudContext.textBaseline = "middle";
  hudContext.fillText(String(number), x, y + 2);
  hudContext.shadowBlur = 0;
  hudContext.textAlign = "start";
  hudContext.textBaseline = "alphabetic";
}

// ---------- HUD ----------
function drawHud(now) {
  hudContext.clearRect(0, 0, view.width, view.height);
  drawObjects(now);
  drawScanLabel(now);
  drawOrb(now);
  drawKissCam(now);
  drawCountdown(now);
  drawHandMusicZones();
  hudContext.lineWidth = 2;
  for (const [key, pointer] of pointers) {
    if (key === "mouse" || !pointer.screen) continue;
    hudContext.strokeStyle = `rgba(${ACCENT_RGB}, 0.75)`;
    hudContext.beginPath();
    for (const [from, to] of HAND_CONNECTIONS) {
      hudContext.moveTo(pointer.screen[from].x, pointer.screen[from].y);
      hudContext.lineTo(pointer.screen[to].x, pointer.screen[to].y);
    }
    hudContext.stroke();
    hudContext.fillStyle = "#bff8ff";
    for (const point of pointer.screen) hudContext.fillRect(point.x - 2, point.y - 2, 4, 4);
    hudContext.beginPath();
    hudContext.arc(pointer.point.x, pointer.point.y, pointer.pinching ? 14 : 9, 0, Math.PI * 2);
    hudContext.fillStyle = pointer.grab ? `rgba(255, 226, 168, 0.85)` : pointer.pinching ? `rgba(${ACCENT_RGB}, 0.6)` : `rgba(${ACCENT_RGB}, 0.2)`;
    hudContext.fill();
  }
  if (face) {
    hudContext.fillStyle = `rgba(255, 226, 168, 0.55)`;
    for (let index = 0; index < face.length; index += 7) hudContext.fillRect(face[index].x - 1, face[index].y - 1, 2, 2);
    const xs = face.map((point) => point.x);
    const ys = face.map((point) => point.y);
    const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    hudContext.strokeStyle = `rgba(255, 226, 168, 0.8)`;
    for (const [x, y, dx, dy] of [[left, top, 1, 1], [right, top, -1, 1], [left, bottom, 1, -1], [right, bottom, -1, -1]]) {
      hudContext.beginPath();
      hudContext.moveTo(x + dx * 18, y);
      hudContext.lineTo(x, y);
      hudContext.lineTo(x, y + dy * 18);
      hudContext.stroke();
    }
    hudContext.fillStyle = `rgba(255, 226, 168, 0.9)`;
    hudContext.font = "600 11px Segoe UI, system-ui, sans-serif";
    hudContext.fillText("FACE LOCK", left, top - 8);
  }
}

// ---------- loop ----------
let lastTime = performance.now();
let fps = 0;
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - lastTime) / 1000);
  lastTime = now;
  holoTime.value = now / 1000;
  fps += ((dt > 0 ? 1 / dt : 0) - fps) * 0.05;
  track(now, dt);
  updateHandMusic(now);
  if (lens !== "normal") lensRenderer.draw(lens, video, now, faceWidth);
  updateKissCam(now);
  updatePhoto(now);
  applyGrabs();
  updateObjects(dt);
  updateParallax();
  renderer.render(scene, camera);
  updateOrb(now, dt);
  drawHud(now);
  if (objectDetector) reportSeen(now);
  if (frameCount % 15 === 0 && window.creative.tracking) {
    const hands = [...pointers.keys()].filter((key) => key !== "mouse").length;
    const seen = shownObjects.map((item) => item.label).join(", ") || "—";
    setStatus(`Hands ${hands} · face ${face ? "locked" : "—"} · sees ${seen} · ${objects.length} holograms${handMusic.on ? ` · 🎵 ${VOICES[handMusic.lastParams?.timbre ?? 0].name} · vol ${handMusic.volume}%` : ""} · ${fps.toFixed(0)} fps`);
  }
}

function resize() {
  view.width = innerWidth;
  view.height = innerHeight;
  renderer.setSize(view.width, view.height);
  hud.width = view.width;
  hud.height = view.height;
  camera.aspect = view.width / view.height;
  camera.updateProjectionMatrix();
  lensRenderer.resize(view.width, view.height);
  layoutOrb();
}

function setStatus(text) { statusLine.textContent = text; }

// ---------- commands from Nova (voice or chat) ----------
function runCommand(command) {
  if (command.action === "add") addShape(command.shape);
  else if (command.action === "explode") setExplode(focus, true);
  else if (command.action === "assemble") setExplode(focus, false);
  else if (command.action === "clear") [...objects].forEach(removeObject);
  else if (command.action === "snapshot") sendSnapshot(false); // "Hey Nova, what am I holding?"
  else if (command.action === "photo") startPhoto();             // "Hey Nova, take a photo"
  else if (command.action === "lens") setLens(command.lens);
  else if (command.action === "kiss_cam") setKissCam(command.on !== false);
  else if (command.action === "hand_music") setHandMusic(command.on !== false);
  else if (command.action === "style") applyStyle(command.style);
  else if (command.action === "label") {
    scanLabel = { text: command.text, box: scanLabel?.box ?? snapshotBox().box, at: performance.now() };
  }
}

async function pollCommands() {
  try {
    const response = await fetch("/commands", { cache: "no-store" });
    if (response.ok) for (const command of await response.json()) runCommand(command);
  } catch {
    // Opened without Nova's server: commands simply aren't available.
  }
  setTimeout(pollCommands, 600);
}

// ---------- controls ----------
document.querySelectorAll("[data-shape]").forEach((button) => button.addEventListener("click", () => addShape(button.dataset.shape)));
document.getElementById("explode").addEventListener("click", () => setExplode(focus, !(focus?.userData.explodeTarget)));
document.getElementById("style").addEventListener("click", () => applyStyle());
applyStyle(style);
document.getElementById("clear").addEventListener("click", () => runCommand({ action: "clear" }));
document.getElementById("toggle-help").addEventListener("click", () => { document.getElementById("help").hidden ^= true; });
document.getElementById("exit").addEventListener("click", exitCreative);
document.getElementById("objects").addEventListener("click", (event) => {
  detectObjects = !detectObjects;
  event.currentTarget.classList.toggle("on", detectObjects);
  if (!detectObjects) shownObjects = [];
});
document.getElementById("file").addEventListener("change", (event) => { for (const file of event.target.files) loadModelFile(file); });
addEventListener("dragover", (event) => { event.preventDefault(); document.body.classList.add("dragging"); });
addEventListener("dragleave", () => document.body.classList.remove("dragging"));
addEventListener("drop", (event) => {
  event.preventDefault();
  document.body.classList.remove("dragging");
  for (const file of event.dataTransfer.files) loadModelFile(file);
});
// Inside Nova's window, Esc closes creative mode there.
document.documentElement.style.setProperty("--accent-rgb", ACCENT_RGB);
addEventListener("keydown", (event) => {
  if (event.key === "Escape" && window.parent !== window) window.parent.postMessage("alfred:close-creative", "*");
  const shapes = ["reactor", "cube", "sphere", "torus", "cone", "cylinder"];
  if (event.key >= "1" && event.key <= "6") addShape(shapes[Number(event.key) - 1]);
  else if (event.key.toLowerCase() === "e") setExplode(focus, !(focus?.userData.explodeTarget));
  else if (event.key.toLowerCase() === "w") applyStyle();
  else if (event.key.toLowerCase() === "c") runCommand({ action: "clear" });
  else if (event.key === " ") { event.preventDefault(); startPhoto(); }
  else if (event.key.toLowerCase() === "l") setLens(LENSES[(LENSES.indexOf(lens) + 1) % LENSES.length]);
  else if (event.key.toLowerCase() === "k") setKissCam(!kissCamOn);
  else if (event.key.toLowerCase() === "m") setHandMusic(!handMusic.on);
});
document.getElementById("photo").addEventListener("click", startPhoto);
document.getElementById("lens-button").addEventListener("click", () => setLens(LENSES[(LENSES.indexOf(lens) + 1) % LENSES.length]));
document.getElementById("kisscam").addEventListener("click", () => setKissCam(!kissCamOn));
document.getElementById("handmusic-button").addEventListener("click", () => setHandMusic(!handMusic.on));
document.getElementById("handmusic-volume").value = String(handMusic.volume);
document.getElementById("handmusic-volume-value").textContent = `${handMusic.volume}%`;
document.getElementById("handmusic-voice").addEventListener("change", (event) => handMusic.instrument.setTimbre(event.target.value));
document.getElementById("handmusic-volume").addEventListener("input", (event) => {
  handMusic.volume = Number(event.target.value);
  document.getElementById("handmusic-volume-value").textContent = `${handMusic.volume}%`;
  handMusic.synth.setVolume(handMusic.volume / 100);
  try { localStorage.setItem("nova-handmusic-volume", String(handMusic.volume)); } catch { /* private mode */ }
});
document.getElementById("handmusic-test").addEventListener("click", async () => {
  try { await handMusic.synth.start(); handMusic.synth.setVolume(handMusic.volume / 100); handMusic.synth.soundCheck(); }
  catch (error) { setStatus(`Hand Music: audio failed to start (${error.message}).`); }
});
addEventListener("resize", resize);

window.creative = { objects, addShape, runCommand, pointers, tracking: false, trackingError: null, orb, fireControl,
  get shownObjects() { return shownObjects; }, get detector() { return Boolean(objectDetector); },
  get scanLabel() { return scanLabel; }, get lens() { return lens; }, get kissCamOn() { return kissCamOn; },
  get photo() { return { ...photo }; }, get faces() { return faces.length; }, setLens, startPhoto };
resize();
addShape("reactor");
requestAnimationFrame(frame);
pollCommands();
startTracking();
