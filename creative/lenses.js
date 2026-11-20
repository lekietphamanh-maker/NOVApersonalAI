// Camera lenses for creative mode: live effects on the mirror, after the camera ideas in
// github.com/tigrisli/curious-machines (01-camera prompts). Pure helpers first (tested in node), then the renderer.

export const LENSES = ["normal", "pixel", "ascii", "glitch", "slitscan", "echo"];
export const LENS_NAMES = { normal: "Normal", pixel: "Pixel", ascii: "ASCII", glitch: "Glitch", slitscan: "Slit-scan", echo: "Echo" };
export const ECHO_SECONDS = 3;
const DEFAULT_RAMP = " .:-=+*#%@";

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

/** Pixel blocks shrink as your face comes closer: people resolve as they walk toward the camera. */
export function pixelBlockSize(faceWidthFraction) {
  if (!faceWidthFraction) return 28;
  return Math.round(clamp(34 - faceWidthFraction * 90, 3, 34));
}

/** The characters of `text` from least to most ink (`inkOf` measures one), starting with a space: the ASCII
 *  lens draws you with the letters of your name. Fewer than 3 different ones: the default ramp. */
export function asciiRamp(text, inkOf) {
  const letters = [...new Set([...String(text ?? "").toUpperCase()].filter((char) => /[A-Z0-9]/.test(char)))];
  if (letters.length < 3) return DEFAULT_RAMP;
  return " " + letters.sort((a, b) => inkOf(a) - inkOf(b)).join("");
}

export const charFor = (ramp, brightness) => ramp[Math.min(ramp.length - 1, Math.max(0, Math.floor(brightness * ramp.length)))];

/** How much changed between two small RGBA frames, 0 (still) to 1. */
export function motionLevel(previous, current) {
  if (!previous || previous.length !== current.length) return 0;
  let total = 0;
  for (let index = 0; index < current.length; index += 4) {
    total += Math.abs(current[index] - previous[index]) + Math.abs(current[index + 1] - previous[index + 1])
      + Math.abs(current[index + 2] - previous[index + 2]);
  }
  return total / (current.length / 4) / (3 * 255);
}

/** Glitch strength from motion: hold still and the picture comes back clean. */
export function glitchAmount(motion) {
  const t = clamp((motion - 0.015) / 0.09, 0, 1);
  return t * t * (3 - 2 * t);
}

/** Kiss cam: exactly two faces held in the picture for `hold` seconds -> one shot, then a pause. */
export function createKissCam({ hold = 3, cooldown = 8 } = {}) {
  let since = null;
  let quietUntil = 0;
  return {
    update(faceCount, seconds) {
      if (faceCount !== 2 || seconds < quietUntil) {
        since = null;
        return { hearts: faceCount === 2, progress: 0, shoot: false };
      }
      since ??= seconds;
      const progress = Math.min(1, (seconds - since) / hold);
      if (progress < 1) return { hearts: true, progress, shoot: false };
      since = null;
      quietUntil = seconds + cooldown;
      return { hearts: true, progress: 1, shoot: true };
    },
  };
}

// ---------- the renderer (browser only) ----------

/** Draws the chosen lens into `canvas` each frame, from the mirrored webcam picture. */
export function createLensRenderer(canvas, accentRgb) {
  const context = canvas.getContext("2d");
  const work = document.createElement("canvas");
  const workContext = work.getContext("2d", { willReadFrequently: true });
  const tiny = Object.assign(document.createElement("canvas"), { width: 32, height: 18 });
  const tinyContext = tiny.getContext("2d", { willReadFrequently: true });
  const slit = Object.assign(document.createElement("canvas"), { width: 480, height: 270 });
  const slitContext = slit.getContext("2d");
  const echoFrames = []; // { canvas, at }
  let echoLast = 0;
  let slitX = 0;
  let previousTiny = null;
  let motion = 0;
  let ramp = DEFAULT_RAMP;
  let cell = { width: 8.4, height: 14 };

  /** The mirrored, cover-fitted camera picture at width x height, in `work`. */
  function grab(video, width, height) {
    work.width = Math.max(1, Math.round(width));
    work.height = Math.max(1, Math.round(height));
    const fit = Math.max(work.width / video.videoWidth, work.height / video.videoHeight);
    const shownWidth = video.videoWidth * fit, shownHeight = video.videoHeight * fit;
    workContext.setTransform(-1, 0, 0, 1, work.width, 0);
    workContext.drawImage(video, (work.width - shownWidth) / 2, (work.height - shownHeight) / 2, shownWidth, shownHeight);
    workContext.setTransform(1, 0, 0, 1, 0, 0);
    return workContext;
  }

  function measureMotion(video) {
    tinyContext.drawImage(video, 0, 0, tiny.width, tiny.height);
    const pixels = tinyContext.getImageData(0, 0, tiny.width, tiny.height).data;
    motion += (motionLevel(previousTiny, pixels) - motion) * 0.3;
    previousTiny = pixels;
  }

  function drawPixel(video, faceWidth) {
    const block = pixelBlockSize(faceWidth);
    grab(video, Math.ceil(canvas.width / block), Math.ceil(canvas.height / block));
    context.imageSmoothingEnabled = false;
    context.drawImage(work, 0, 0, work.width * block, work.height * block);
  }

  function drawAscii(video) {
    const columns = Math.floor(canvas.width / cell.width), rows = Math.floor(canvas.height / cell.height);
    const pixels = grab(video, columns, rows).getImageData(0, 0, columns, rows).data;
    let low = 1, high = 0; // stretch the contrast: webcams are often dim
    const light = new Float32Array(columns * rows);
    for (let index = 0; index < light.length; index++) {
      const value = (0.299 * pixels[index * 4] + 0.587 * pixels[index * 4 + 1] + 0.114 * pixels[index * 4 + 2]) / 255;
      light[index] = value;
      low = Math.min(low, value);
      high = Math.max(high, value);
    }
    const span = Math.max(0.15, high - low);
    context.fillStyle = "#000";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = `rgb(${accentRgb})`;
    context.font = `600 ${cell.height}px "JetBrains Mono", Consolas, monospace`;
    context.textBaseline = "top";
    for (let row = 0; row < rows; row++) {
      let line = "";
      for (let column = 0; column < columns; column++) line += charFor(ramp, (light[row * columns + column] - low) / span);
      context.fillText(line, 0, row * cell.height);
    }
  }

  function drawGlitch(video, now) {
    const amount = glitchAmount(motion);
    const width = 480, height = Math.round(480 * canvas.height / canvas.width);
    const source = grab(video, width, height).getImageData(0, 0, width, height);
    if (amount > 0.02) {
      const from = source.data, out = new Uint8ClampedArray(from.length);
      const split = Math.round(amount * 14);
      const offsets = new Int32Array(height);
      const bands = Math.round(amount * 9);
      let seed = Math.floor(now / 90); // new tears a few times a second, not every frame
      const random = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
      for (let band = 0; band < bands; band++) {
        const top = Math.floor(random() * height), size = 2 + Math.floor(random() * height * 0.08);
        const shift = Math.round((random() - 0.5) * 80 * amount);
        for (let y = top; y < Math.min(height, top + size); y++) offsets[y] = shift;
      }
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const at = (y * width + x) * 4;
          const sx = clamp(x + offsets[y], 0, width - 1);
          out[at] = from[(y * width + clamp(sx + split, 0, width - 1)) * 4];
          out[at + 1] = from[(y * width + sx) * 4 + 1];
          out[at + 2] = from[(y * width + clamp(sx - split, 0, width - 1)) * 4 + 2];
          out[at + 3] = 255;
        }
      }
      source.data.set(out);
    }
    workContext.putImageData(source, 0, 0);
    context.imageSmoothingEnabled = true;
    context.drawImage(work, 0, 0, canvas.width, canvas.height);
  }

  function drawSlitscan(video) {
    // Each frame adds the middle column of the picture: whatever crosses the middle is stretched over time.
    grab(video, slit.width, slit.height);
    slitContext.drawImage(work, slit.width / 2 - 1, 0, 2, slit.height, slitX, 0, 2, slit.height);
    slitX = (slitX + 2) % slit.width;
    context.imageSmoothingEnabled = true;
    context.drawImage(slit, 0, 0, canvas.width, canvas.height);
    const x = (slitX / slit.width) * canvas.width;
    context.fillStyle = `rgba(${accentRgb}, 0.8)`;
    context.fillRect(x, 0, 2, canvas.height);
  }

  function drawEcho(video, now) {
    if (now - echoLast > 66) { // ~15 pictures a second, small: a few seconds fit in ~25 MB
      echoLast = now;
      const frame = echoFrames.length && now - echoFrames[0].at > ECHO_SECONDS * 1000 ? echoFrames.shift().canvas
        : document.createElement("canvas");
      frame.width = 480;
      frame.height = Math.round(480 * canvas.height / canvas.width);
      grab(video, frame.width, frame.height);
      frame.getContext("2d").drawImage(work, 0, 0);
      echoFrames.push({ canvas: frame, at: now });
    }
    const past = echoFrames[0];
    context.imageSmoothingEnabled = true;
    context.drawImage(past.canvas, 0, 0, canvas.width, canvas.height);
    context.fillStyle = `rgba(${accentRgb}, 0.9)`;
    context.font = `600 13px "JetBrains Mono", Consolas, monospace`;
    context.textBaseline = "top";
    context.fillText(`− ${((now - past.at) / 1000).toFixed(1)} s`, canvas.width / 2 - 30, 64);
  }

  return {
    get motion() { return motion; },
    /** The ASCII lens writes with these letters (the owner's name), measured for ink once. */
    setName(name) {
      const probe = Object.assign(document.createElement("canvas"), { width: 24, height: 24 }).getContext("2d", { willReadFrequently: true });
      probe.font = `600 20px "JetBrains Mono", Consolas, monospace`;
      probe.textBaseline = "top";
      const inkOf = (char) => {
        probe.clearRect(0, 0, 24, 24);
        probe.fillText(char, 2, 1);
        return probe.getImageData(0, 0, 24, 24).data.filter((_value, index) => index % 4 === 3 && _value > 0).length;
      };
      ramp = asciiRamp(name || "NOVA", inkOf);
      context.font = `600 ${cell.height}px "JetBrains Mono", Consolas, monospace`;
      cell = { width: context.measureText("M").width || 8.4, height: 14 };
    },
    resize(width, height) {
      canvas.width = width;
      canvas.height = height;
      context.font = `600 ${cell.height}px "JetBrains Mono", Consolas, monospace`;
      cell = { width: context.measureText("M").width || 8.4, height: 14 };
    },
    reset() {
      echoFrames.length = 0;
      slitContext.clearRect(0, 0, slit.width, slit.height);
      slitX = 0;
    },
    draw(lens, video, now, faceWidth) {
      if (video.readyState < 2 || !video.videoWidth) return;
      measureMotion(video);
      if (lens === "pixel") drawPixel(video, faceWidth);
      else if (lens === "ascii") drawAscii(video);
      else if (lens === "glitch") drawGlitch(video, now);
      else if (lens === "slitscan") drawSlitscan(video);
      else if (lens === "echo") drawEcho(video, now);
    },
  };
}
