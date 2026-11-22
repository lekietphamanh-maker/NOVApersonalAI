// Hand Music synth: a self-contained Web Audio instrument. No samples, no dependencies.
//
// The shape follows the lab's FieldSynth idea (a few inharmonic voices through a filter, a delay
// and a limiter) but this is Nova's own implementation. Two rules from the lab are kept exactly:
//  - one deliberate contact excites one *finite* phrase. Tracking alone is silent, and a pinch
//    never drones: every envelope decays to zero on its own.
//  - a zone entry plays a short tuned ping; an exit plays nothing.
//
// Output: the synth connects to the AudioContext destination — the system default output, the same
// output Nova's voice speaks through. There is deliberately no output-device picker here (Keith
// asked for default output only). The master volume is kept modest for an external speaker:
// default 0.5, capped at 0.8, and a limiter sits in front of the output so a loud gesture can't
// clip the speaker.
export const VOICES = Object.freeze([
  { name: "Porcelain", base: 261.63, partials: [1, 2.756, 4.07], levels: [0.5, 0.11, 0.04], types: ["sine", "sine", "sine"], noise: 0, attack: 0.012, duration: 1.65 },
  { name: "String", base: 220.0, partials: [1, 2, 3], levels: [0.42, 0.12, 0.05], types: ["triangle", "sine", "sine"], noise: 0, attack: 0.022, duration: 2.2 },
  { name: "Air", base: 349.23, partials: [1, 1.5, 2], levels: [0.17, 0.07, 0.03], types: ["sine", "sine", "sine"], noise: 0.1, attack: 0.09, duration: 1.5 },
]);

export const ZONE_PINGS = Object.freeze([
  { zone: "A", freq: 293.66, pan: -0.4, dur: 0.42 }, // D3, left
  { zone: "B", freq: 392.0, pan: 0, dur: 0.5 },     // G4, centre
  { zone: "C", freq: 440.0, pan: 0.4, dur: 0.58 },  // A4, right
]);

const bound = (x, a, b) => Math.min(b, Math.max(a, Number.isFinite(x) ? x : a));
const lerp = (a, b, t) => a + (b - a) * t;

export class HandMusicSynth {
  constructor() {
    this.ctx = null; this.ready = false; this.muted = true;
    this.voice = 0; this.volume = 0.5; this.maxVolume = 0.8;
    this.lastGate = 0; this.lastExcitation = -Infinity; this.lastFrameMs = -Infinity;
    this.activePings = 0; this.pings = new Set(); this.startPromise = null;
  }

  async start() {
    if (this.ready) return this.resume();
    if (this.startPromise) return this.startPromise;
    this.startPromise = this._start();
    try { return await this.startPromise; } finally { this.startPromise = null; }
  }

  async _start() {
    const AC = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AC) throw new Error("Web Audio is unavailable in this browser");
    const ctx = this.ctx = new AC({ latencyHint: "interactive" });
    try {
      await ctx.resume();
      if (ctx.state !== "running") throw new Error("Audio is suspended. Tap START AUDIO again.");
      // Chain: voices -> highpass -> lowpass -> dry/delay -> mix -> limiter -> master -> destination.
      // Destination is the default output: the same speaker Nova's voice uses.
      this.source = ctx.createGain(); this.source.gain.value = 0;
      this.highpass = ctx.createBiquadFilter(); this.highpass.type = "highpass"; this.highpass.frequency.value = 150; this.highpass.Q.value = 0.6;
      this.filter = ctx.createBiquadFilter(); this.filter.type = "lowpass"; this.filter.frequency.value = 1900; this.filter.Q.value = 0.7;
      this.delay = ctx.createDelay(0.7); this.delay.delayTime.value = 0.19;
      this.feedback = ctx.createGain(); this.feedback.gain.value = 0.1;
      this.wetGain = ctx.createGain(); this.wetGain.gain.value = 0.08;
      this.dryGain = ctx.createGain(); this.dryGain.gain.value = 0.85;
      this.tailGate = ctx.createGain(); this.tailGate.gain.value = 0;
      this.pan = ctx.createStereoPanner(); this.pan.pan.value = 0;
      const mix = ctx.createGain(); mix.gain.value = 0.52;
      this.limiter = ctx.createDynamicsCompressor();
      this.limiter.threshold.value = -12; this.limiter.knee.value = 8; this.limiter.ratio.value = 10;
      this.limiter.attack.value = 0.004; this.limiter.release.value = 0.14;
      this.master = ctx.createGain(); this.master.gain.value = this.volume;
      this.analyser = ctx.createAnalyser(); this.analyser.fftSize = 256;
      this.levelData = new Uint8Array(this.analyser.fftSize);
      this.source.connect(this.highpass); this.highpass.connect(this.filter);
      this.filter.connect(this.dryGain); this.dryGain.connect(mix);
      this.filter.connect(this.delay); this.delay.connect(this.wetGain); this.wetGain.connect(mix);
      this.delay.connect(this.feedback); this.feedback.connect(this.delay);
      mix.connect(this.tailGate); this.tailGate.connect(this.pan); this.pan.connect(this.limiter);
      this.limiter.connect(this.master); this.master.connect(this.analyser); this.analyser.connect(ctx.destination);
      this.osc = [];
      for (let i = 0; i < 3; i++) {
        const osc = ctx.createOscillator(), gain = ctx.createGain();
        osc.type = "sine"; gain.gain.value = 0; osc.connect(gain); gain.connect(this.source); osc.start();
        this.osc.push({ osc, gain });
      }
      // Quiet breath material for the Air voice only, gated by the same finite envelope.
      const buffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      let seed = 173;
      for (let i = 0; i < data.length; i++) { seed = (seed * 1664525 + 1013904223) >>> 0; data[i] = seed / 2147483648 - 1; }
      this.noise = ctx.createBufferSource(); this.noise.buffer = buffer; this.noise.loop = true;
      this.noiseGain = ctx.createGain(); this.noiseGain.gain.value = 0;
      const breath = ctx.createBiquadFilter(); breath.type = "bandpass"; breath.frequency.value = 1550; breath.Q.value = 0.65;
      this.noise.connect(breath); breath.connect(this.noiseGain); this.noiseGain.connect(this.source); this.noise.start();
      this._voice(0, ctx.currentTime);
      this.ready = true; this.muted = false;
    } catch (error) {
      this.ready = false; this.muted = true;
      try { await ctx.close(); } catch { /* already closed */ }
      this.ctx = null; this.osc = [];
      throw error;
    }
  }

  _voice(index, t) {
    this.voice = Math.round(bound(Number(index), 0, 2));
    const v = VOICES[this.voice];
    this.osc.forEach(({ osc, gain }, i) => {
      osc.type = v.types[i];
      osc.frequency.setTargetAtTime(v.base * v.partials[i], t, 0.04);
      gain.gain.setTargetAtTime(v.levels[i], t, 0.04);
    });
    this.noiseGain.gain.setTargetAtTime(v.noise, t, 0.04);
  }

  /** Master volume, 0..1, capped so an external speaker never gets a hot signal. */
  setVolume(value) {
    this.volume = bound(Number(value), 0, this.maxVolume);
    if (this.ready && !this.muted) this.master.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.025);
    return this.volume;
  }

  _excite(energy, t) {
    const v = VOICES[this.voice];
    const peak = lerp(0.21, 0.46, energy);
    const g = this.source.gain;
    g.cancelScheduledValues(t); g.setValueAtTime(0, t);
    g.linearRampToValueAtTime(peak, t + v.attack);
    g.exponentialRampToValueAtTime(0.0001, t + v.duration);
    g.setValueAtTime(0, t + v.duration + 0.025);
    const tail = this.tailGate.gain;
    tail.cancelScheduledValues(t); tail.setValueAtTime(1, t);
    tail.setValueAtTime(1, t + v.duration); tail.linearRampToValueAtTime(0, t + v.duration + 0.65);
    this.lastExcitation = t;
  }

  release() {
    if (!this.ready) return;
    const t = this.ctx.currentTime;
    this.lastGate = 0;
    this.source.gain.cancelScheduledValues(t);
    this.source.gain.setTargetAtTime(0, t, 0.02);
    this.source.gain.setValueAtTime(0, t + 0.12);
    this.tailGate.gain.cancelScheduledValues(t);
    this.tailGate.gain.setTargetAtTime(0, t, 0.07);
    this.tailGate.gain.setValueAtTime(0, t + 0.42);
  }

  /** One frame of gesture params. Gate edges always process; a throttle must never swallow a release. */
  update(params = {}, nowMs = 0) {
    if (!this.ready || this.muted || this.ctx.state !== "running") return;
    const ctx = this.ctx, t = ctx.currentTime;
    const gate = bound(params.gate, 0, 1);
    const active = this.lastGate ? gate > 0.2 : gate >= 0.35;
    const voice = Math.round(bound(Number(params.timbre) || 0, 0, 2));
    if (voice !== this.voice) this._voice(voice, t);
    if (active && !this.lastGate && t - this.lastExcitation > 0.07) this._excite(bound(params.energy, 0, 1), t);
    else if (!active && this.lastGate) this.release();
    this.lastGate = active ? 1 : 0;
    if (nowMs - this.lastFrameMs < 13) return;
    this.lastFrameMs = nowMs;
    const sm = (param, value, ramp = 0.04) => param.setTargetAtTime(value, t, ramp);
    sm(this.filter.frequency, 650 * Math.pow(4400 / 650, bound(params.cutoff, 0, 1)));
    sm(this.filter.Q, lerp(0.45, 2.2, bound(params.resonance, 0, 1)));
    sm(this.wetGain.gain, lerp(0.035, 0.18, bound(params.wet, 0, 1)));
    sm(this.pan.pan, lerp(-0.8, 0.8, bound(params.spread, 0, 1)));
    sm(this.feedback.gain, lerp(0.07, 0.17, bound(params.drive, 0, 1)));
  }

  /** A zone entry plays a short tuned ping (panned per zone). Exits play nothing. */
  triggerZone(zoneId, amp = 1) {
    if (!this.ready || this.muted || this.ctx.state !== "running" || this.activePings >= 12) return false;
    const ping = ZONE_PINGS.find((p) => p.zone === zoneId);
    if (!ping) return false;
    const ctx = this.ctx, t = ctx.currentTime + 0.008;
    const o = ctx.createOscillator(), g = ctx.createGain(), p = ctx.createStereoPanner();
    o.type = "sine"; o.frequency.value = ping.freq; p.pan.value = ping.pan;
    const peak = bound(0.025 + amp * 0.045, 0.008, 0.08);
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(peak, t + 0.009);
    g.gain.exponentialRampToValueAtTime(0.0001, t + ping.dur);
    g.gain.setValueAtTime(0, t + ping.dur + 0.01);
    o.connect(g); g.connect(p); p.connect(this.master);
    this.activePings++; this.pings.add(o);
    o.onended = () => { if (this.pings.delete(o)) this.activePings--; o.disconnect(); g.disconnect(); p.disconnect(); };
    o.start(t); o.stop(t + ping.dur + 0.025);
    return true;
  }

  soundCheck() { return this.triggerZone("A", 0.6); }

  /** Stop everything now: used when tracking is lost or the mode is turned off. */
  async panic() {
    this.muted = true;
    if (!this.ctx || !this.master) return;
    const t = this.ctx.currentTime;
    this.release();
    this.master.gain.cancelScheduledValues(t);
    this.master.gain.setTargetAtTime(0, t, 0.01);
    this.master.gain.setValueAtTime(0, t + 0.05);
    for (const ping of this.pings) { try { ping.stop(t + 0.01); } catch { /* already stopped */ } }
    this.pings.clear(); this.activePings = 0;
  }

  async resume() {
    if (!this.ready) return this.start();
    await this.ctx.resume();
    if (this.ctx.state !== "running") { this.muted = true; throw new Error("Audio remains suspended. Tap START AUDIO again."); }
    // Resume quietly: old held gestures and delay tails cannot restart a drone.
    this.release();
    this.master.gain.cancelScheduledValues(this.ctx.currentTime);
    this.master.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.04);
    this.muted = false;
  }

  meter() {
    if (!this.analyser || !this.levelData) return 0;
    this.analyser.getByteTimeDomainData(this.levelData);
    let sum = 0;
    for (const v of this.levelData) { const d = (v - 128) / 128; sum += d * d; }
    return Math.sqrt(sum / this.levelData.length);
  }
}
