"""The widget's voice call, in plain ES5-ish JavaScript, loaded only when it is needed (#54, Q8).

Separate from `WIDGET_JS` so the bubble every visitor downloads stays small: the
widget fetches this the first time a visitor opens it, and only when its public
config says calls are on. It speaks `/embed/{public_key}/voice/ws` exactly as
the console's call view speaks `/ws/voice` (`app.schemas.voice`): WebRTC with no
data channel where the public config says `webrtc`, 16-bit PCM over the socket
where it says `relay`, with the `played` reports barge-in needs.

The call view is the console's inline call bar, cut down for a bubble on
somebody else's page: the input row becomes a bar with a level meter in the
operator's accent, the state, the time against the call's limit, Mute and End;
spoken turns land in the message list as captions and are replaced by the
saved messages; one line under the bar says what went wrong. No glow, no
push-to-talk and no approval card - a visitor's calls carry no tool that needs
an approval. English copy, like the rest of the widget.

**Everything is closed on End, on the socket closing, on the peer connection
failing, on the visitor closing the panel and on `pagehide`** - the peer
connection, the microphone, the audio context and the socket. A peer
connection left open is an OpenAI call still billing; the server hangs up
too, but the page does not lean on that. One dropped connection is retried once,
as `resume_of` the call it continues, within the server's ten-second window.

`__PUBLIC_KEY__` and `__BASE_URL__` are substituted when it is served. It
registers itself under its own key, so two widgets on one page each mount their
own call, and `mount` returns the handle the widget ends the call through.
"""

import hashlib

VOICE_JS = r"""(function () {
  var KEY = "__PUBLIC_KEY__";
  var BASE = "__BASE_URL__";
  // The server accepts a resumed call for ten seconds after the old connection
  // ended; the retry waits a moment first, so that connection's teardown is done,
  // and stops trying a little inside the window, as the console's call does.
  var RESUME_DELAY_MS = 1500;
  var RESUME_WINDOW_MS = 8000;
  // How often the relay reports how much of the agent's audio has played, while
  // it changes. Barge-in cuts at the last report.
  var PLAYED_EVERY_MS = 100;
  // After End, how long the socket stays open for the turns the server saves on
  // the way out.
  var LINGER_MS = 5000;
  var INK = "#334155";
  var STATES = {
    connecting: "Connecting…",
    listening: "Listening",
    user_speaking: "Listening",
    interrupted: "Listening",
    thinking: "Thinking…",
    tool_running: "Working…",
    awaiting_approval: "Working…",
    agent_speaking: "Speaking"
  };
  var COPY = {
    start: "Start a voice call",
    reconnecting: "Reconnecting…",
    ended: "Call ended.",
    failed: "The call couldn't connect. Please try again.",
    dropped: "The call dropped. Press the call button to call again.",
    refused: "Calls aren't available on this page.",
    too_many: "Too many calls just now - wait a moment and try again.",
    unsupported: "This browser can't make calls. Try a current Chrome, Edge, Firefox or Safari.",
    mic_denied: "The microphone is blocked for this site. Allow it in your browser's site settings, then try again.",
    mic_not_found: "No microphone found. Connect one, then try again.",
    mic_busy: "The microphone didn't start. Another app may be using it.",
    mic_insecure: "This page can't use the microphone: browsers allow it only on HTTPS.",
    dictating: "Finish the dictation first, then start the call.",
    guardrail: "Part of the answer was held back.",
    provider_error: "The voice service had a problem. If the assistant stays silent, end the call and try again."
  };
  // Why a call ended or was refused, by the server's reason. Anything not here -
  // an error, or a setup problem that is the operator's to fix - is the fallback.
  var ENDED = {
    user: COPY.ended,
    time_limit: "The call reached its time limit.",
    call_limit: "The call reached its time limit.",
    minutes: "No call minutes are left this month. Please type your message instead.",
    minutes_exhausted: "No call minutes are left this month. Please type your message instead.",
    budget: "This assistant can't take calls right now. Please type your message instead.",
    line_busy: "All lines are busy. Try again in a few minutes, or type your message.",
    voice_off: "Calls are switched off here.",
    revoked: "Calls were switched off here.",
    guardrail: "The call was ended by a content rule.",
    shutdown: "The server restarted. Press the call button to call again.",
    disconnected: COPY.dropped,
    resume_refused: COPY.dropped
  };
  var ENDED_FALLBACK = "The call ended unexpectedly. Please try again.";
  var CALL_ICON = ["M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"];
  var MIC_ICON = ["M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v3"];
  var MIC_OFF_ICON = ["M12 19v3", "M15 9.34V5a3 3 0 0 0-5.68-1.33", "M16.95 16.95A7 7 0 0 1 5 12v-2",
    "M18.89 13.23A7 7 0 0 0 19 12v-2", "m2 2 20 20", "M9 9v3a3 3 0 0 0 5.12 2.12"];

  // A server-sent name looked up in one of the tables above, and only there: a
  // kind called `constructor` must not print the Object prototype's.
  function lookup(table, name) {
    return Object.prototype.hasOwnProperty.call(table, name) ? table[name] : null;
  }

  function el(tag, style, text) {
    var node = document.createElement(tag);
    if (style) node.setAttribute("style", style);
    if (text) node.textContent = text;
    return node;
  }

  function icon(paths) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    var attributes = { viewBox: "0 0 24 24", width: "18", height: "18", fill: "none", stroke: "currentColor",
      "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" };
    for (var name in attributes) svg.setAttribute(name, attributes[name]);
    for (var i = 0; i < paths.length; i += 1) {
      var path = document.createElementNS(ns, "path");
      path.setAttribute("d", paths[i]);
      svg.appendChild(path);
    }
    return svg;
  }

  function clock(seconds) {
    var whole = Math.max(0, Math.floor(seconds));
    var rest = whole % 60;
    return Math.floor(whole / 60) + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function micFailure(error) {
    var name = error && error.name;
    if (name === "NotAllowedError" || name === "SecurityError") return "mic_denied";
    if (name === "NotFoundError" || name === "OverconstrainedError") return "mic_not_found";
    return "mic_busy";
  }

  // What the page says about the visitor, as a text message carries it - only
  // the flat values the server reads, so a nested object on the page cannot
  // make the whole start frame invalid.
  function pageContext() {
    var supplied = window.AgenticOSContext;
    if (!supplied || typeof supplied !== "object") return null;
    var out = {};
    var count = 0;
    for (var name in supplied) {
      if (!Object.prototype.hasOwnProperty.call(supplied, name) || count >= 64) continue;
      var value = supplied[name];
      var kind = typeof value;
      if (value === null || kind === "string" || kind === "boolean" || (kind === "number" && isFinite(value))) {
        out[name] = value;
        count += 1;
      }
    }
    return count ? out : null;
  }

  // The relay's audio, dictation's approach (#1797): a ScriptProcessorNode
  // rather than a worklet, which is a module by URL the host page's CSP may
  // refuse; mixed to mono, resampled by averaging the samples each output spans,
  // and sent as 16-bit little-endian PCM at the model's input rate.
  function mixToMono(channels) {
    var length = channels[0].length;
    for (var c = 1; c < channels.length; c += 1) length = Math.min(length, channels[c].length);
    var mono = new Float32Array(length);
    for (var k = 0; k < channels.length; k += 1) {
      for (var i = 0; i < length; i += 1) mono[i] += channels[k][i] / channels.length;
    }
    return mono;
  }

  function createResampler(fromRate, toRate) {
    var ratio = fromRate / toRate;
    var consumed = 0;
    var produced = 0;
    var pending = new Float32Array(0);
    return function (chunk) {
      var input = new Float32Array(pending.length + chunk.length);
      input.set(pending);
      input.set(chunk, pending.length);
      var output = [];
      for (;;) {
        var start = Math.floor(produced * ratio) - consumed;
        var end = Math.max(Math.floor((produced + 1) * ratio) - consumed, start + 1);
        if (end > input.length) break;
        var sum = 0;
        for (var i = start; i < end; i += 1) sum += input[i];
        output.push(sum / (end - start));
        produced += 1;
      }
      var drop = Math.floor(produced * ratio) - consumed;
      pending = input.subarray(drop);
      consumed += drop;
      return new Float32Array(output);
    };
  }

  function toPcm16(samples) {
    var buffer = new ArrayBuffer(samples.length * 2);
    var view = new DataView(buffer);
    for (var i = 0; i < samples.length; i += 1) {
      var clipped = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
    }
    return buffer;
  }

  // Plays the agent's PCM chunks back to back and counts what has played, in
  // the bytes the server sent: audio dropped on `clear_playback` counts as
  // passed, which is what the server's `played` position expects.
  function createPlayer(context, rate, output, onDrained) {
    var queued = [];
    var passed = 0;
    var next = 0;
    function stopAll() {
      for (var i = 0; i < queued.length; i += 1) {
        try { queued[i].node.stop(); } catch (e) { /* already ended */ }
        queued[i].node.disconnect();
        passed += queued[i].bytes;
      }
      queued = [];
      next = 0;
    }
    return {
      enqueue: function (pcm) {
        var samples = Math.floor(pcm.byteLength / 2);
        if (!samples) return;
        var buffer = context.createBuffer(1, samples, rate);
        var channel = buffer.getChannelData(0);
        var view = new DataView(pcm);
        for (var i = 0; i < samples; i += 1) channel[i] = view.getInt16(i * 2, true) / 0x8000;
        var node = context.createBufferSource();
        node.buffer = buffer;
        node.connect(output);
        var start = Math.max(context.currentTime, next);
        node.start(start);
        next = start + samples / rate;
        var item = { node: node, start: start, end: next, bytes: samples * 2 };
        queued.push(item);
        node.onended = function () { if (queued[queued.length - 1] === item) onDrained(); };
      },
      played: function () {
        var now = context.currentTime;
        while (queued.length && queued[0].end <= now) {
          var done = queued.shift();
          done.node.disconnect();
          passed += done.bytes;
        }
        var playing = queued[0];
        if (!playing || now <= playing.start) return passed;
        var fraction = (now - playing.start) / (playing.end - playing.start);
        return passed + Math.floor((fraction * playing.bytes) / 2) * 2;
      },
      clear: stopAll
    };
  }

  function mount(parts, config) {
    var accent = config.accent;
    var still = reducedMotion();
    var call = null;

    var button = el("button", "border:0;border-radius:10px;padding:0 10px;cursor:pointer;background:transparent;color:#475569;display:flex;align-items:center");
    button.setAttribute("type", "button");
    button.setAttribute("aria-label", COPY.start);
    button.setAttribute("title", COPY.start);
    button.appendChild(icon(CALL_ICON));
    parts.form.insertBefore(button, parts.send);

    var bar = el("div", "display:none;flex:1;align-items:center;gap:8px;min-width:0");
    var meter = el("div", "flex:1;height:6px;border-radius:3px;background:#e2e8f0;overflow:hidden;min-width:24px");
    var level = el("div", "height:100%;width:0;border-radius:3px;background:" + accent);
    meter.appendChild(level);
    var label = el("div", "font-size:13px;color:#0f172a;white-space:nowrap");
    label.setAttribute("aria-live", "polite");
    var timer = el("div", "font-size:12px;color:#475569;font-variant-numeric:tabular-nums;white-space:nowrap");
    var mute = el("button", "border:0;border-radius:10px;padding:8px;cursor:pointer;background:transparent;color:#475569;display:flex;align-items:center");
    mute.setAttribute("type", "button");
    mute.appendChild(icon(MIC_ICON));
    var end = el("button", "border:0;border-radius:10px;padding:10px 14px;font-size:14px;font-weight:600;color:#fff;cursor:pointer;background:#dc2626", "End");
    end.setAttribute("type", "button");
    end.setAttribute("aria-label", "End call");
    bar.appendChild(meter);
    bar.appendChild(label);
    bar.appendChild(timer);
    bar.appendChild(mute);
    bar.appendChild(end);
    parts.form.appendChild(bar);

    var notice = el("div", "display:none;padding:0 14px 10px;font-size:12px;line-height:1.45;color:#475569;background:#fff");
    notice.setAttribute("role", "status");
    parts.panel.insertBefore(notice, parts.form.nextSibling);

    function say(text, error) {
      notice.textContent = text || "";
      notice.style.display = text ? "block" : "none";
      notice.style.color = error ? "#b91c1c" : "#475569";
    }

    var hidden = [];
    function showBar(on) {
      if (on) {
        hidden = [];
        for (var i = 0; i < parts.form.children.length; i += 1) {
          var child = parts.form.children[i];
          if (child === bar) continue;
          hidden.push([child, child.style.display]);
          child.style.display = "none";
        }
        bar.style.display = "flex";
        end.focus();
        return;
      }
      for (var k = 0; k < hidden.length; k += 1) hidden[k][0].style.display = hidden[k][1];
      hidden = [];
      bar.style.display = "none";
      level.style.width = "0";
      timer.textContent = "";
    }

    function showState(c) {
      var text = c.reconnecting ? COPY.reconnecting : lookup(STATES, c.state) || STATES.thinking;
      if (c.muted && text === STATES.listening) text = "Muted";
      label.textContent = text;
    }

    function syncMute(c) {
      mute.setAttribute("aria-pressed", c && c.muted ? "true" : "false");
      mute.setAttribute("aria-label", c && c.muted ? "Unmute microphone" : "Mute microphone");
      mute.setAttribute("title", c && c.muted ? "Unmute" : "Mute");
      mute.style.color = c && c.muted ? "#b91c1c" : "#475569";
      // Crossed out while muted, as the console's Mute is: colour alone says nothing to some eyes.
      var drawn = mute.children[0];
      if (drawn) drawn.remove();
      mute.appendChild(icon(c && c.muted ? MIC_OFF_ICON : MIC_ICON));
    }

    // Captions, one bubble a turn: the parts of the agent's answer are joined,
    // and the saved message replaces them when it lands.
    var turns = {};
    function bubbleFor(turnId, role) {
      var turn = turns[turnId];
      if (!turn) turn = turns[turnId] = { body: parts.bubble(role === "user" ? "user" : "assistant", ""), parts: {}, order: [], saved: false };
      return turn;
    }
    function caption(frame) {
      var turn = bubbleFor(frame.turn_id, frame.role);
      if (turn.saved) return;
      if (!(frame.part in turn.parts)) { turn.order.push(frame.part); turn.parts[frame.part] = ""; }
      if (typeof frame.delta === "string") turn.parts[frame.part] += frame.delta;
      else if (typeof frame.final === "string") turn.parts[frame.part] = frame.final;
      else if (typeof frame.text === "string") turn.parts[frame.part] = frame.text;
      var text = [];
      for (var i = 0; i < turn.order.length; i += 1) if (turn.parts[turn.order[i]]) text.push(turn.parts[turn.order[i]]);
      turn.body.textContent = text.join(" ");
      parts.log.scrollTop = parts.log.scrollHeight;
    }
    function saved(message) {
      if (!message || typeof message.turn_id !== "string") return;
      var content = typeof message.content === "string" ? message.content : "";
      if (!turns[message.turn_id] && !content) return;
      var turn = bubbleFor(message.turn_id, message.role);
      turn.saved = true;
      if (content) turn.body.textContent = content;
      else if (!turn.body.textContent) { turn.body.parentNode.remove(); return; }
      if (message.interrupted) turn.body.appendChild(el("span", "display:block;margin-top:4px;font-size:11px;opacity:.7", "Interrupted"));
      parts.log.scrollTop = parts.log.scrollHeight;
    }

    function analyse(c, source) {
      var analyser = c.context.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      return analyser;
    }
    function loudness(analyser, samples) {
      if (!analyser) return 0;
      analyser.getFloatTimeDomainData(samples);
      var sum = 0;
      for (var i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      return Math.min(1, Math.sqrt(sum / samples.length) * 7);
    }
    // One bar for both voices: the visitor's in ink, the agent's in the
    // operator's accent, whichever is louder. Under reduced motion it holds one
    // of five steps rather than following the voice frame by frame.
    function watchLevel(c) {
      var samples = new Float32Array(1024);
      var smoothed = 0;
      var shown = -1;
      function sample() {
        if (c.done) return;
        var mine = c.muted ? 0 : loudness(c.micAnalyser, samples);
        var theirs = loudness(c.agentAnalyser, samples);
        var target = Math.max(mine, theirs);
        smoothed += (target - smoothed) * (target > smoothed ? 0.35 : 0.08);
        var width = still ? Math.round(smoothed * 5) * 20 : Math.round(smoothed * 100);
        if (width !== shown) {
          shown = width;
          level.style.width = width + "%";
          level.style.background = theirs >= mine ? accent : INK;
        }
        c.frame = requestAnimationFrame(sample);
      }
      c.frame = requestAnimationFrame(sample);
    }

    function tick(c) {
      if (!c.startedAt) return;
      var now = Date.now();
      timer.textContent = clock((now - c.startedAt) / 1000) + " / " + clock((c.endsAt - c.startedAt) / 1000);
    }

    function send(c, frame) {
      if (c.socket && c.socket.readyState === 1) c.socket.send(JSON.stringify(frame));
    }

    // Everything this connection carries, but not the microphone or the audio
    // context: a reconnect keeps those.
    function closeMedia(c) {
      if (c.pc) { c.pc.close(); c.pc = null; }
      if (c.relay) {
        clearInterval(c.relay.timer);
        c.relay.player.clear();
        for (var i = 0; i < c.relay.nodes.length; i += 1) c.relay.nodes[i].disconnect();
        c.relay = null;
      }
      if (c.remote) { c.remote.disconnect(); c.remote = null; }
      c.agentAnalyser = null;
      c.audio.srcObject = null;
    }

    // The call is over on this page: every resource closed, the input row back.
    // `linger` keeps the socket open a moment after End for the turns the server
    // saves on the way out; it is closed after `LINGER_MS` whatever happens.
    function finish(c, text, error, linger) {
      if (c.done) return;
      c.done = true;
      if (call === c) call = null;
      // Focus goes back to the call button only from the bar being taken away;
      // a visitor who had moved on elsewhere is left where they are.
      var focused = bar.contains(document.activeElement);
      clearTimeout(c.retry);
      clearInterval(c.ticker);
      if (c.frame) cancelAnimationFrame(c.frame);
      closeMedia(c);
      if (c.mic) {
        var tracks = c.mic.getTracks();
        for (var i = 0; i < tracks.length; i += 1) tracks[i].stop();
        c.mic = null;
      }
      if (c.context.close) c.context.close();
      var socket = c.socket;
      if (socket) {
        if (linger && socket.readyState === 1) c.linger = setTimeout(function () { socket.close(); }, LINGER_MS);
        else socket.close();
      }
      showBar(false);
      syncMute(null);
      say(text, error);
      if (focused) button.focus();
    }

    function hangUp(c, linger) {
      send(c, { type: "end" });
      finish(c, COPY.ended, false, linger);
    }

    // The call cannot carry audio: hung up at once, so a call the visitor cannot
    // hear is not left running - and billing - behind a "Listening" label.
    function fail(c) {
      send(c, { type: "end" });
      finish(c, COPY.failed, true);
    }

    function startRelay(c, frame) {
      var context = c.context;
      if (!context.createScriptProcessor) return false;
      var resample = createResampler(context.sampleRate, frame.input_sample_rate);
      var source = context.createMediaStreamSource(c.mic);
      var processor = context.createScriptProcessor(4096, 2, 1);
      // A processor runs only while connected to the destination; the gain at
      // zero keeps the microphone out of the speakers.
      var silent = context.createGain();
      silent.gain.value = 0;
      processor.onaudioprocess = function (event) {
        var socket = c.socket;
        if (!socket || socket.readyState !== 1) return;
        var channels = [];
        for (var i = 0; i < event.inputBuffer.numberOfChannels; i += 1) channels.push(event.inputBuffer.getChannelData(i));
        var pcm = resample(mixToMono(channels));
        if (pcm.length) socket.send(toPcm16(pcm));
      };
      source.connect(processor);
      processor.connect(silent);
      silent.connect(context.destination);
      var output = context.createGain();
      output.connect(context.destination);
      c.agentAnalyser = analyse(c, output);
      var reported = 0;
      function report() {
        var bytes = player.played();
        if (bytes === reported) return;
        reported = bytes;
        send(c, { type: "played", bytes: bytes });
      }
      var player = createPlayer(context, frame.output_sample_rate, output, report);
      c.relay = { nodes: [source, processor, silent, output], player: player, timer: setInterval(report, PLAYED_EVERY_MS) };
      return true;
    }

    function onReady(c, frame) {
      if (frame.transport !== c.transport) { fail(c); return; }
      if (frame.transport === "relay" && !startRelay(c, frame)) { hangUp(c, false); say(COPY.unsupported, true); return; }
      c.callId = frame.call_id;
      c.reconnecting = false;
      if (!c.startedAt) c.startedAt = Date.now();
      // On a resumed call the server sends what is left of the call's time.
      c.endsAt = Date.now() + frame.cap_seconds * 1000;
      // A resumed call starts unmuted on the server; the visitor muted this one.
      if (c.muted) send(c, { type: "mute", muted: true });
      tick(c);
      say("");
      showState(c);
    }

    function onFrame(c, frame) {
      if (frame.type === "answer" && c.pc) {
        c.pc.setRemoteDescription({ type: "answer", sdp: frame.sdp }).catch(function () { fail(c); });
      } else if (frame.type === "state") { c.state = frame.state; showState(c); }
      else if (frame.type === "caption") caption(frame);
      else if (frame.type === "turn_saved") saved(frame.message);
      else if (frame.type === "clear_playback") { if (c.relay) c.relay.player.clear(); }
      else if (frame.type === "notice") say(lookup(COPY, frame.kind) || lookup(ENDED, frame.kind) || "", frame.kind !== "guardrail");
      else if (frame.type === "limit") say(clock(frame.seconds_left) + " left in this call.", false);
      else if (frame.type === "ended") finish(c, lookup(ENDED, frame.reason) || ENDED_FALLBACK, frame.reason !== "user");
    }

    function offer(c) {
      var pc = c.pc = new RTCPeerConnection();
      var tracks = c.mic.getAudioTracks();
      for (var i = 0; i < tracks.length; i += 1) pc.addTrack(tracks[i], c.mic);
      // A site whose network blocks the media path connects the socket but no
      // audio: the peer connection says so, and nothing else would.
      pc.onconnectionstatechange = function () {
        if (c.pc === pc && pc.connectionState === "failed") fail(c);
      };
      pc.oniceconnectionstatechange = function () {
        if (c.pc === pc && pc.iceConnectionState === "failed") fail(c);
      };
      pc.ontrack = function (event) {
        var stream = event.streams[0];
        if (!stream || c.done) return;
        c.audio.srcObject = stream;
        if (c.audio.play) c.audio.play().catch(function () { /* autoplay is allowed after the click */ });
        c.remote = c.context.createMediaStreamSource(stream);
        c.agentAnalyser = analyse(c, c.remote);
      };
      return pc.createOffer().then(function (made) { return pc.setLocalDescription(made); }).then(function () {
        var sdp = pc.localDescription.sdp;
        // One audio stream and nothing else: the server refuses a data channel too.
        if (/^m=application/im.test(sdp) || !/^m=audio/im.test(sdp)) throw new Error("offer");
        return sdp;
      });
    }

    function schedule(c, resumeOf) {
      c.retry = setTimeout(function () { connect(c, resumeOf); }, RESUME_DELAY_MS);
    }

    function connect(c, resumeOf) {
      var setup = c.transport === "relay" ? Promise.resolve(null) : offer(c);
      // `.catch` after the whole setup, so a throw inside it - a WebSocket the
      // page's CSP refuses, say - still releases the microphone and the context.
      setup.then(function (sdp) {
        if (c.done) return;
        var url = BASE.replace(/^http/, "ws") + "/api/v1/embed/" + KEY + "/voice/ws";
        var token = window.AgenticOSToken;
        if (token) url += "?token=" + encodeURIComponent(token);
        var socket = c.socket = new WebSocket(url);
        socket.binaryType = "arraybuffer";
        var ready = false;
        socket.onopen = function () {
          var start = { type: "start" };
          if (sdp) start.sdp_offer = sdp;
          if (resumeOf) start.resume_of = resumeOf;
          var context = pageContext();
          if (context) start.context = context;
          socket.send(JSON.stringify(start));
        };
        socket.onmessage = function (event) {
          if (c.socket !== socket) return;
          if (typeof event.data !== "string") {
            if (!c.done && c.relay) c.relay.player.enqueue(event.data);
            return;
          }
          var frame;
          try { frame = JSON.parse(event.data); } catch (e) { return; }
          if (c.done) {
            // After End only the turns saved on the way out still count.
            if (frame.type === "turn_saved") saved(frame.message);
            if (frame.type === "ended") { clearTimeout(c.linger); socket.close(); }
            return;
          }
          if (frame.type === "ready") { ready = true; onReady(c, frame); }
          else onFrame(c, frame);
        };
        socket.onclose = function (event) {
          if (c.socket !== socket) return;
          c.socket = null;
          if (c.done) return;
          closeMedia(c);
          if (event.code === 4003) { finish(c, COPY.refused, true); return; }
          if (event.code === 4029) { finish(c, COPY.too_many, true); return; }
          if (resumeOf && !ready && Date.now() < c.resumeUntil) { schedule(c, resumeOf); return; }
          if (!c.callId || c.retried) { finish(c, c.callId ? COPY.dropped : COPY.failed, true); return; }
          // One automatic retry, as the call it continues.
          c.retried = true;
          c.reconnecting = true;
          c.resumeUntil = Date.now() + RESUME_WINDOW_MS;
          showState(c);
          schedule(c, c.callId);
        };
      }).catch(function () { fail(c); });
    }

    function start() {
      if (call) return;
      // Not while a dictation is recording: its bar has the input row.
      if (parts.input.style.display === "none") { say(COPY.dictating, false); return; }
      var Context = window.AudioContext || window.webkitAudioContext;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        say(window.isSecureContext === false ? COPY.mic_insecure : COPY.unsupported, true);
        return;
      }
      var transport = config.voice_transport === "relay" ? "relay" : "webrtc";
      if (!Context || (transport === "webrtc" && !window.RTCPeerConnection)) { say(COPY.unsupported, true); return; }
      // Made inside the click, which the browser counts as the visitor's gesture:
      // made after the permission prompt it may start suspended and play nothing.
      var c = call = { transport: transport, context: new Context(), audio: new Audio(), state: "connecting" };
      c.audio.autoplay = true;
      say("");
      syncMute(c);
      showBar(true);
      showState(c);
      c.ticker = setInterval(function () { tick(c); }, 1000);
      navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      }).then(function (stream) {
        if (c.done) {
          var tracks = stream.getTracks();
          for (var i = 0; i < tracks.length; i += 1) tracks[i].stop();
          return;
        }
        c.mic = stream;
        c.micSource = c.context.createMediaStreamSource(stream);
        c.micAnalyser = analyse(c, c.micSource);
        watchLevel(c);
        connect(c, null);
      }, function (error) { finish(c, COPY[micFailure(error)], true); });
    }

    button.onclick = start;
    end.onclick = function () { if (call) hangUp(call, true); };
    mute.onclick = function () {
      var c = call;
      if (!c) return;
      c.muted = !c.muted;
      if (c.mic) {
        var tracks = c.mic.getAudioTracks();
        for (var i = 0; i < tracks.length; i += 1) tracks[i].enabled = !c.muted;
      }
      send(c, { type: "mute", muted: c.muted });
      syncMute(c);
      showState(c);
    };
    // Leaving the page ends the call there and then, without waiting for anything.
    window.addEventListener("pagehide", function () { if (call) hangUp(call, false); });
    // What the widget calls when the visitor closes the panel: a call with no
    // End button on screen would go on billing out of sight, so it ends too.
    return { end: function () { if (call) hangUp(call, true); } };
  }

  window.AgenticOSVoice = window.AgenticOSVoice || {};
  window.AgenticOSVoice[KEY] = mount;
})();
"""

VOICE_JS_VERSION = hashlib.sha256(VOICE_JS.encode()).hexdigest()[:16]
"""The script's content hash. `widget.js` asks for `voice.js?v=<this>`, so a deploy
that changes the call script changes the URL the widget fetches, and a browser
holding an old copy cannot pair it with a newer widget; that URL is cached for good."""
