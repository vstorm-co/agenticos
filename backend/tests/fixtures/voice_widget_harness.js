// Drives the widget's call script (`voice.js`) through one scenario in node,
// against a fake DOM, microphone, Web Audio, peer connection and socket, and
// prints what happened as JSON for `tests/test_embed_voice_js.py` to assert on.
//
//   node voice_widget_harness.js <rendered voice.js> <scenario> <webrtc|relay>
"use strict";
const fs = require("fs");

function El(tag) { this.tagName = tag; this.children = []; this.style = {}; this.attrs = {}; this.parentNode = null; this.textContent = ""; }
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.appendChild = function (c) { c.parentNode = this; this.children.push(c); return c; };
El.prototype.insertBefore = function (c, ref) {
  c.parentNode = this;
  const i = ref ? this.children.indexOf(ref) : -1;
  if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
  return c;
};
El.prototype.remove = function () { const p = this.parentNode; if (p) p.children.splice(p.children.indexOf(this), 1); };
El.prototype.focus = function () { document.activeElement = this; };
El.prototype.contains = function (n) { for (; n; n = n.parentNode) if (n === this) return true; return false; };
Object.defineProperty(El.prototype, "nextSibling", { get() { const p = this.parentNode; return p.children[p.children.indexOf(this) + 1] || null; } });

global.document = { activeElement: null, createElement: (t) => new El(t), createElementNS: (_, t) => new El(t) };
const listeners = {};
global.window = global;
window.addEventListener = (name, fn) => { listeners[name] = fn; };
window.matchMedia = () => ({ matches: false });
global.requestAnimationFrame = () => 1;
global.cancelAnimationFrame = () => {};
let timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = () => {};
global.setInterval = () => 1;
global.clearInterval = () => {};

const track = { enabled: true, stopped: false, stop() { this.stopped = true; } };
const mic = { getTracks: () => [track], getAudioTracks: () => [track] };
Object.defineProperty(global, "navigator", { value: { mediaDevices: { getUserMedia: () => Promise.resolve(mic) } } });

function AudioNodeFake() {}
AudioNodeFake.prototype.connect = function () {};
AudioNodeFake.prototype.disconnect = function () {};
let contextClosed = false;
global.AudioContext = function () { this.sampleRate = 48000; this.currentTime = 0; this.destination = new AudioNodeFake(); };
Object.assign(AudioContext.prototype, {
  createAnalyser: () => Object.assign(new AudioNodeFake(), { getFloatTimeDomainData() {} }),
  createMediaStreamSource: () => new AudioNodeFake(),
  createScriptProcessor: () => new AudioNodeFake(),
  createGain: () => Object.assign(new AudioNodeFake(), { gain: {} }),
  createBuffer: (_, n) => ({ getChannelData: () => new Float32Array(n) }),
  createBufferSource: () => Object.assign(new AudioNodeFake(), { start() {}, stop() {} }),
  close: () => { contextClosed = true; return Promise.resolve(); },
});
global.Audio = function () {};

const peers = [];
global.RTCPeerConnection = function () { this.closed = false; peers.push(this); };
Object.assign(RTCPeerConnection.prototype, {
  addTrack() {},
  createOffer: () => Promise.resolve({ type: "offer", sdp: "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n" }),
  setLocalDescription(d) { this.localDescription = d; return Promise.resolve(); },
  setRemoteDescription: () => Promise.resolve(),
  close() { this.closed = true; },
});

const sockets = [];
let refuseSockets = false;
global.WebSocket = function (url) {
  if (refuseSockets) throw new Error("refused by the page's CSP");
  this.url = url; this.readyState = 0; this.sent = []; this.closed = false; sockets.push(this);
};
WebSocket.prototype.send = function (d) { this.sent.push(d); };
WebSocket.prototype.close = function () { this.readyState = 3; this.closed = true; };

eval(fs.readFileSync(process.argv[2], "utf8"));

const settle = () => new Promise((r) => setImmediate(r));
async function settled() { for (let i = 0; i < 5; i += 1) await settle(); }
const form = new El("form"), input = new El("input"), send = new El("button"), panel = new El("div"), log = new El("div");
input.style.display = "";
form.appendChild(input); form.appendChild(send); panel.appendChild(log); panel.appendChild(form);
const bubble = (role, text) => { const row = new El("div"); const b = new El("div"); b.role = role; b.textContent = text; row.appendChild(b); log.appendChild(row); return b; };
const transport = process.argv[4];
const handle = Object.values(window.AgenticOSVoice)[0]({ form, input, send, panel, log, bubble }, { accent: "#4f46e5", voice_transport: transport });
const callButton = form.children[1];
const bar = form.children[3];
const notice = panel.children.find((n) => n.attrs.role === "status");
const frame = (socket, f) => socket.onmessage({ data: JSON.stringify(f) });
const ready = (socket, callId) => frame(socket, { type: "ready", transport, call_id: callId, input_sample_rate: 24000, output_sample_rate: 24000, cap_seconds: 600, resume_token: `secret-of-${callId}` });
const frames = (socket) => socket.sent.filter((d) => typeof d === "string").map((d) => JSON.parse(d));
const bubbles = () => log.children.map((row) => row.children[0].role + ": " + row.children[0].textContent + (row.children[0].children.length ? " [" + row.children[0].children[0].textContent + "]" : ""));
async function call() {
  callButton.onclick();
  await settled();
  const socket = sockets[sockets.length - 1];
  socket.readyState = 1;
  socket.onopen();
  return socket;
}
function state(extra) {
  return Object.assign({
    sockets: sockets.length,
    starts: sockets.map((s) => (frames(s)[0] || {}).resume_of || null),
    startSecrets: sockets.map((s) => (frames(s)[0] || {}).resume_token || null),
    notice: notice.textContent,
    barShown: bar.style.display === "flex",
    inputShown: input.style.display === "",
    micStopped: track.stopped,
    contextClosed,
    peersClosed: peers.every((p) => p.closed),
    socketsClosed: sockets.every((s) => s.closed),
    endSent: sockets.some((s) => frames(s).some((f) => f.type === "end")),
    pendingTimers: timers.length,
  }, extra);
}

const scenarios = {
  async call() {
    const socket = await call();
    const start = frames(socket)[0];
    ready(socket, "c1");
    frame(socket, { type: "state", state: "agent_speaking" });
    frame(socket, { type: "caption", role: "user", turn_id: "c1:1:user", part: 0, delta: "What is " });
    frame(socket, { type: "caption", role: "user", turn_id: "c1:1:user", part: 0, delta: "the time" });
    const live = bubbles();
    frame(socket, { type: "turn_saved", message: { turn_id: "c1:1:user", role: "user", content: "What is the time?", interrupted: false } });
    frame(socket, { type: "caption", role: "assistant", turn_id: "c1:2:assistant", part: 1, delta: "It is noon, " });
    frame(socket, { type: "turn_saved", message: { turn_id: "c1:2:assistant", role: "assistant", content: "It is noon,", interrupted: true } });
    const label = bar.children[1].textContent;
    bar.children[4].onclick();
    const ended = state({ start, live, label, saved: bubbles() });
    frame(socket, { type: "ended", reason: "user" });
    return Object.assign(ended, { closedOnEnded: socket.closed });
  },
  async drop() {
    let socket = await call();
    ready(socket, "c1");
    bar.children[3].onclick();
    const muteIcon = bar.children[3].children.flatMap((svg) => svg.children.map((path) => path.attrs.d));
    socket.onclose({ code: 1006 });
    const label = bar.children[1].textContent;
    timers.shift()();
    await settled();
    socket = sockets[1];
    socket.readyState = 1;
    socket.onopen();
    ready(socket, "c2");
    const resumedFrames = frames(socket);
    socket.onclose({ code: 1006 });
    return state({ label, resumedFrames, muteIcon });
  },
  async refused() {
    const socket = await call();
    socket.onclose({ code: 4003 });
    return state();
  },
  async too_many() {
    const socket = await call();
    socket.onclose({ code: 4029 });
    return state();
  },
  async line_busy() {
    const socket = await call();
    frame(socket, { type: "ended", reason: "line_busy", message: "Too many calls are open here right now." });
    socket.onclose({ code: 1000 });
    return state();
  },
  async pagehide() {
    const socket = await call();
    ready(socket, "c1");
    listeners.pagehide();
    return state();
  },
  async panel_closed() {
    const socket = await call();
    ready(socket, "c1");
    handle.end();
    // The socket waits for the turns saved on the way out, then closes regardless.
    const lingered = !socket.closed;
    timers.splice(0).forEach((fn) => fn());
    return state({ lingered });
  },
  async media_failed() {
    const socket = await call();
    ready(socket, "c1");
    peers[0].connectionState = "failed";
    peers[0].onconnectionstatechange();
    return state();
  },
  async setup_threw() {
    refuseSockets = true;
    callButton.onclick();
    await settled();
    return state();
  },
  async odd_names() {
    const socket = await call();
    ready(socket, "c1");
    frame(socket, { type: "notice", kind: "constructor" });
    const afterNotice = notice.textContent;
    frame(socket, { type: "ended", reason: "toString" });
    return state({ afterNotice });
  },
  async dictating() {
    input.style.display = "none";
    callButton.onclick();
    await settled();
    return state();
  },
};

scenarios[process.argv[3]]().then(
  (result) => { process.stdout.write(JSON.stringify(result)); },
  (error) => { process.stderr.write(String(error && error.stack)); process.exit(1); },
);
