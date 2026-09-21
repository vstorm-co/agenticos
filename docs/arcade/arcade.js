/* The arcade's shared half: one harness, three cabinets.
 *
 * Every game here grows the same agent. What a player collects in the runner is
 * still there in the canyon, because all three read and write one record in
 * `localStorage` - that record is the point of the arcade, and the games are
 * three ways of filling it in.
 *
 * Amigo himself is transcribed from `docs/assets/amigo.svg`, one letter per
 * pixel, so the sprite on screen and the mascot in the README are the same
 * drawing rather than two that drifted apart.
 */
(function (global) {
  "use strict";

  var KEY = "agenticos.arcade.harness.v1";
  var REPO = "https://github.com/vstorm-co/agenticos";

  /* The harness catalogue. Each part is a real thing an AgenticOS agent is
   * given - a capability, a skill, a context file, a memory, an MCP server -
   * and each carries a perk that changes how the games play, so the collection
   * is a progression and not a sticker album. */
  var PARTS = [
    {
      id: "tool.web_search",
      kind: "tool",
      name: "Web search",
      blurb: "It looks things up instead of guessing.",
      where: "Desert Run",
      how: "Bank 30 tokens in one shift",
      perk: "Tokens pull toward Amigo from further away.",
    },
    {
      id: "tool.browser",
      kind: "tool",
      name: "Browser control",
      blurb: "It drives a real browser, clicks and all.",
      where: "Capability Canyon",
      how: "Reach the publish flag",
      perk: "A second jump in mid-air, everywhere.",
    },
    {
      id: "tool.charts",
      kind: "tool",
      name: "Charts",
      blurb: "Numbers come back as a picture, not a paragraph.",
      where: "Desert Run",
      how: "Survive a full minute",
      perk: "The budget meter holds a fifth more.",
    },
    {
      id: "skill.retry",
      kind: "skill",
      name: "Retry policy",
      blurb: "A failed call is retried with a backoff instead of surfacing.",
      where: "Desert Run",
      how: "Fail three shifts - failure is the curriculum",
      perk: "One free hit per run, in the runner and the canyon.",
    },
    {
      id: "skill.compaction",
      kind: "skill",
      name: "Context compaction",
      blurb: "A long conversation is folded down before it overflows.",
      where: "Capability Canyon",
      how: "Bank 40 tokens in one run",
      perk: "The budget drains a quarter slower.",
    },
    {
      id: "skill.handoff",
      kind: "skill",
      name: "Delegation",
      blurb: "Work it should not do itself goes to a sub-agent.",
      where: "Night Shift",
      how: "Close every ticket inside three minutes",
      perk: "Amigo walks faster on the shift floor.",
    },
    {
      id: "skill.structured",
      kind: "skill",
      name: "Structured output",
      blurb: "Pydantic AI validates the answer into a typed model, or refuses it.",
      where: "Capability Canyon",
      how: "Take the schema orb above the spikes",
      perk: "Hallucinations drift slower - structure tames them.",
    },
    {
      id: "context.playbook",
      kind: "context",
      name: "Company playbook",
      blurb: "Standing knowledge bound to the agent, not pasted per message.",
      where: "Night Shift",
      how: "Work a shift through to the end",
      perk: "The shift shows you which station is next.",
    },
    {
      id: "context.brand",
      kind: "context",
      name: "Brand voice",
      blurb: "It answers in the company's words rather than the model's.",
      where: "The arcade",
      how: "Play all three cabinets",
      perk: "Amigo's poncho picks up a gold trim.",
    },
    {
      id: "memory.session",
      kind: "memory",
      name: "Session memory",
      blurb: "It remembers the last thing you said. Only that far.",
      where: "Capability Canyon",
      how: "Take the knowledge orb out of the drop",
      perk: "The canyon restarts at your last checkpoint.",
    },
    {
      id: "memory.long_term",
      kind: "memory",
      name: "Long-term memory",
      blurb: "What it learned last week survives into this one.",
      where: "Night Shift",
      how: "Work two full shifts",
      perk: "A fourth heart in the canyon.",
    },
    {
      id: "data.vectors",
      kind: "data",
      name: "Embedded documents",
      blurb: "Chunked, embedded and searchable by meaning in pgvector.",
      where: "Capability Canyon",
      how: "Collect three document chunks in one run",
      perk: "The canyon map shows every capability, playbook or not.",
    },
    {
      id: "data.clean",
      kind: "data",
      name: "Clean customer data",
      blurb: "The CRM export, minus the duplicates, the nulls and the test rows.",
      where: "Night Shift",
      how: "Take the messy export through the parser",
      perk: "Half as much bad data blows across the desert.",
    },
    {
      id: "mcp.github",
      kind: "mcp",
      name: "GitHub MCP",
      blurb: "Issues, pull requests and releases, from a chat message.",
      where: "Any continue screen",
      how: "Open the repository",
      perk: "Bragging rights, and the arcade stops nagging you.",
    },
    {
      id: "mcp.linear",
      kind: "mcp",
      name: "Linear MCP",
      blurb: "One connection, fourteen tools, three of them allowed.",
      where: "Night Shift",
      how: "Carry the tool back to the chat desk",
      perk: "A sixth ticket lands on the shift.",
    },
    {
      id: "mcp.gdrive",
      kind: "mcp",
      name: "Google Drive MCP",
      blurb: "A shared drive the agent can read, with the sharing rules intact.",
      where: "Night Shift",
      how: "Connect the drive the sales folder lives on",
      perk: "An extra document chunk appears in the canyon.",
    },
    {
      id: "mcp.notion",
      kind: "mcp",
      name: "Notion MCP",
      blurb: "The team wiki, as pages the agent can search and write back to.",
      where: "Capability Canyon",
      how: "Find the page hidden past the second drop",
      perk: "The night shift names every station on your route.",
    },
    {
      id: "model.claude",
      kind: "model",
      name: "Claude Opus",
      blurb: "The default here: long context, careful with tools.",
      where: "Desert Run",
      how: "Catch the Anthropic chip",
      perk: "Careful calls: the budget drains a tenth slower.",
    },
    {
      id: "model.gpt",
      kind: "model",
      name: "GPT",
      blurb: "The one everybody already has a key for.",
      where: "Desert Run",
      how: "Catch the OpenAI chip",
      perk: "Every token pickup counts double.",
    },
    {
      id: "model.qwen",
      kind: "model",
      name: "Qwen",
      blurb: "Open weights, run on your own hardware, no per-token invoice.",
      where: "Night Shift",
      how: "Answer the thirty-thousand-dollar invoice",
      perk: "Self-hosted: the first fifteen seconds of a run are free.",
    },
    {
      id: "model.deepseek",
      kind: "model",
      name: "DeepSeek",
      blurb: "Reasoning at a price that does not need a meeting.",
      where: "Capability Canyon",
      how: "Find the chip at the bottom of the deep drop",
      perk: "Cheap tokens: each one refills more budget.",
    },
    {
      id: "vstorm.badge",
      kind: "vstorm",
      name: "Vstorm badge",
      blurb: "The people who build this. Rare, and it shows.",
      where: "Desert Run",
      how: "Catch the badge - it only flies past once in a while",
      perk: "Amigo wears the colours, and every shift starts with a bigger budget.",
    },
  ];

  var KINDS = {
    tool: { label: "Capabilities", color: "#2e8b57" },
    skill: { label: "Skills", color: "#f2c14e" },
    context: { label: "Context", color: "#3d9fb5" },
    memory: { label: "Memory", color: "#9b59b6" },
    data: { label: "Knowledge", color: "#d4763a" },
    mcp: { label: "MCP", color: "#4b6bdd" },
    model: { label: "Models", color: "#c8412b" },
    vstorm: { label: "Vstorm", color: "#7b5cf0" },
  };

  var DEFAULT_STATE = {
    v: 1,
    unlocked: [],
    played: [],
    stats: {
      runnerBest: 0,
      runnerRuns: 0,
      runnerDeaths: 0,
      runnerLongest: 0,
      canyonClears: 0,
      canyonBestTokens: 0,
      canyonDepth: 0,
      shiftClears: 0,
      shiftBest: 0,
      lifetimeTokens: 0,
    },
  };

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  /* Every read and write is wrapped: a private window, blocked site data or a
   * thumbnail capture all answer with a throw rather than an empty string, and
   * a game that cannot save is still a game. */
  function read() {
    var state = clone(DEFAULT_STATE);
    try {
      var raw = global.localStorage.getItem(KEY);
      if (!raw) return state;
      var saved = JSON.parse(raw);
      if (!saved || saved.v !== 1) return state;
      if (Array.isArray(saved.unlocked)) state.unlocked = saved.unlocked.slice();
      if (Array.isArray(saved.played)) state.played = saved.played.slice();
      if (saved.stats) {
        Object.keys(state.stats).forEach(function (key) {
          if (typeof saved.stats[key] === "number") state.stats[key] = saved.stats[key];
        });
      }
    } catch (err) {
      return clone(DEFAULT_STATE);
    }
    return state;
  }

  function write(state) {
    try {
      global.localStorage.setItem(KEY, JSON.stringify(state));
    } catch (err) {
      /* Nothing to do and nothing worth saying: the run still counts, it just
       * does not outlive the tab. */
    }
    return state;
  }

  var listeners = [];

  function emit(event) {
    listeners.forEach(function (fn) {
      fn(event);
    });
  }

  var Harness = {
    all: PARTS,
    kinds: KINDS,
    repo: REPO,

    state: read,

    part: function (id) {
      var found = null;
      PARTS.forEach(function (p) {
        if (p.id === id) found = p;
      });
      return found;
    },

    has: function (id) {
      return read().unlocked.indexOf(id) !== -1;
    },

    /* Returns the part when it was newly unlocked, and null when the player
     * already had it - which is what decides whether a toast fires. */
    unlock: function (id) {
      var part = Harness.part(id);
      if (!part) return null;
      var state = read();
      if (state.unlocked.indexOf(id) !== -1) return null;
      state.unlocked.push(id);
      write(state);
      emit({ type: "unlock", part: part });
      return part;
    },

    played: function (game) {
      var state = read();
      if (state.played.indexOf(game) === -1) {
        state.played.push(game);
        write(state);
      }
      if (read().played.length >= 3) Harness.unlock("context.brand");
    },

    /* `best` keeps the larger number, `add` accumulates, `set` overwrites. The
     * shift's clock is the one stat where smaller is better, so it is stored
     * through `best` as a negative and read back by the hub. */
    record: function (patch) {
      var state = read();
      Object.keys(patch).forEach(function (key) {
        var entry = patch[key];
        var current = state.stats[key] || 0;
        if (entry.best !== undefined) state.stats[key] = Math.max(current, entry.best);
        else if (entry.add !== undefined) state.stats[key] = current + entry.add;
        else if (entry.set !== undefined) state.stats[key] = entry.set;
      });
      write(state);
      return state.stats;
    },

    stats: function () {
      return read().stats;
    },

    reset: function () {
      write(clone(DEFAULT_STATE));
      emit({ type: "reset" });
    },

    on: function (fn) {
      listeners.push(fn);
    },
  };

  /* Amigo, 16 by 19. Rows 0 to 16 are the body; the legs swap per frame exactly
   * the way `docs/assets/amigo-walk.svg` swaps them. */
  var PALETTE = {
    ".": null,
    K: "#4a2c17",
    H: "#d99a5b",
    R: "#8e1b1b",
    F: "#f1c27d",
    W: "#ffffff",
    E: "#1a1f2e",
    M: "#5b3a1e",
    P: "#c8412b",
    G: "#2e8b57",
    Y: "#f2c14e",
  };

  var BODY = [
    "......KKKK......",
    ".....KHHHHK.....",
    "....KHHHHHHK....",
    "KHHHHHHHHHHHHHHK",
    ".KRRRRRRRRRRRRK.",
    "....KFFFFFFK....",
    "....KWEFFWEK....",
    "....KEEFFEEK....",
    "....KEEFFEEK....",
    "...KMMMFFMMMK...",
    "...KPPPPPPPPK...",
    "..KPPGGGGGGPPK..",
    ".KPPPPPPPPPPPPK.",
    ".KPGGGGGGGGGGPK.",
    ".KPPPPPPPPPPPPK.",
    ".KPYYYYYYYYYYPK.",
    ".KKKKKKKKKKKKKK.",
  ];

  var LEGS = {
    stand: ["....KKK..KKK....", "....KKK..KKK...."],
    step: ["...KKK....KKK...", "...KKK....KKK..."],
    air: ["...KK......KK...", "..KK........KK.."],
    tuck: ["...KKKK..KKKK...", "................"],
  };

  function bake(legs, palette) {
    var rows = BODY.concat(LEGS[legs]);
    var canvas = global.document.createElement("canvas");
    canvas.width = 16;
    canvas.height = rows.length;
    var g = canvas.getContext("2d");
    rows.forEach(function (row, y) {
      for (var x = 0; x < row.length; x++) {
        var color = palette[row[x]];
        if (!color) continue;
        g.fillStyle = color;
        g.fillRect(x, y, 1, 1);
      }
    });
    return canvas;
  }

  /* One cosmetic, earned rather than chosen: the brand-voice context file turns
   * the poncho's bottom band gold and warms the green stripes to match. */
  function paletteFor(state) {
    var palette = {};
    Object.keys(PALETTE).forEach(function (key) {
      palette[key] = PALETTE[key];
    });
    if (state.unlocked.indexOf("context.brand") !== -1) {
      palette.G = "#c79a2e";
      palette.Y = "#ffe9a8";
    }
    if (state.unlocked.indexOf("vstorm.badge") !== -1) {
      palette.R = "#7b5cf0";
    }
    return palette;
  }

  function sprites() {
    var palette = paletteFor(read());
    return {
      stand: bake("stand", palette),
      step: bake("step", palette),
      air: bake("air", palette),
      tuck: bake("tuck", palette),
    };
  }

  /* The shell every cabinet shares: a toast for an unlock, and the continue
   * screen with the repository button on it. */
  function toast(host, message, tone) {
    var el = host.querySelector(".arc-toast");
    if (!el) {
      el = global.document.createElement("div");
      el.className = "arc-toast";
      host.appendChild(el);
    }
    el.textContent = message;
    el.dataset.tone = tone || "plain";
    el.classList.add("is-shown");
    global.clearTimeout(el._timer);
    el._timer = global.setTimeout(function () {
      el.classList.remove("is-shown");
    }, 2600);
  }

  function unlockToast(host, part) {
    if (!part) return;
    Sound.play(part.kind === "vstorm" ? "vstorm" : "unlock");
    toast(host, "Harness upgraded: " + part.name + " - " + part.perk, "unlock");
  }

  var NAGS = [
    "Continue? Insert one GitHub star.",
    "The agent respawns. The repository does not star itself.",
    "Amigo works for free. A star is the tip.",
    "This cabinet accepts stars only.",
  ];

  /* The continue screen. The repository button is the joke and the call to
   * action at once, and opening it is what connects the GitHub MCP server -
   * the one part of the harness you cannot earn by playing well. */
  function continueScreen(options) {
    var nag = NAGS[Math.floor(Math.random() * NAGS.length)];
    var stats = (options.stats || [])
      .map(function (row) {
        return '<span><b>' + row[0] + "</b>" + row[1] + "</span>";
      })
      .join("");
    return (
      '<h2 class="' +
      (options.won ? "is-win" : "") +
      '">' +
      options.title +
      "</h2>" +
      (options.reason ? '<p class="arc-reason">' + options.reason + "</p>" : "") +
      (options.note ? "<p>" + options.note + "</p>" : "") +
      (stats ? '<div class="arc-tally">' + stats + "</div>" : "") +
      '<p class="arc-nag">' +
      nag +
      "</p>" +
      '<div class="arc-actions">' +
      '<button type="button" class="arc-btn is-primary" data-action="retry">' +
      (options.retryLabel || "Run it again") +
      "</button>" +
      '<a class="arc-btn is-repo" data-action="repo" href="' +
      REPO +
      '" target="_blank" rel="noopener">Open the repo</a>' +
      "</div>" +
      '<p class="arc-hint">Space to continue · <a href="./">back to the arcade</a></p>'
    );
  }

  /* Wires the two buttons a continue screen has. The repository link is allowed
   * to do its own navigation; the unlock rides along on the same click. */
  function wireContinue(overlay, onRetry) {
    if (!overlay.hasAttribute("tabindex")) overlay.setAttribute("tabindex", "-1");
    if (!overlay.hidden) {
      try {
        overlay.focus({ preventScroll: true });
      } catch (err) {
        overlay.focus();
      }
    }
    var retry = overlay.querySelector('[data-action="retry"]');
    if (retry) {
      retry.addEventListener("click", function () {
        onRetry();
      });
    }
    var repo = overlay.querySelector('[data-action="repo"]');
    if (repo) {
      repo.addEventListener("click", function () {
        var part = Harness.unlock("mcp.github");
        if (part) unlockToast(overlay.parentNode, part);
      });
    }
  }

  /* Sound, synthesised on the spot.
   *
   * No files: every effect here is one or two oscillators and a noise burst
   * through a gain envelope, which keeps the arcade a handful of text files and
   * means nothing has to load before the first jump. The context is built on
   * the first gesture, because a browser refuses to start audio before one, and
   * the preference survives in `localStorage` - a muted arcade stays muted.
   */
  var SOUND_KEY = "agenticos.arcade.sound.v1";

  var Sound = (function () {
    var ctx = null;
    var master = null;
    var on = true;

    try {
      on = global.localStorage.getItem(SOUND_KEY) !== "off";
    } catch (err) {
      on = true;
    }

    function wake() {
      if (!on) return null;
      if (!ctx) {
        var Ctor = global.AudioContext || global.webkitAudioContext;
        if (!Ctor) return null;
        ctx = new Ctor();
        master = ctx.createGain();
        master.gain.value = 0.22;
        master.connect(ctx.destination);
      }
      if (ctx.state === "suspended") ctx.resume();
      return ctx;
    }

    /* One voice: a shape, a pitch that may slide, and an envelope. Everything
     * the games ask for is built out of a few of these. */
    function tone(opts) {
      var c = wake();
      if (!c) return;
      var at = c.currentTime + (opts.delay || 0);
      var osc = c.createOscillator();
      var gain = c.createGain();
      osc.type = opts.type || "square";
      osc.frequency.setValueAtTime(opts.from, at);
      if (opts.to && opts.to !== opts.from) {
        osc.frequency.exponentialRampToValueAtTime(Math.max(20, opts.to), at + opts.dur);
      }
      var peak = opts.gain === undefined ? 0.5 : opts.gain;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(peak, at + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + opts.dur);
      osc.connect(gain);
      gain.connect(master);
      osc.start(at);
      osc.stop(at + opts.dur + 0.02);
    }

    /* Noise, for anything that is an impact rather than a note. */
    function noise(opts) {
      var c = wake();
      if (!c) return;
      var at = c.currentTime + (opts.delay || 0);
      var frames = Math.floor(c.sampleRate * opts.dur);
      var buffer = c.createBuffer(1, frames, c.sampleRate);
      var data = buffer.getChannelData(0);
      for (var i = 0; i < frames; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / frames);
      var src = c.createBufferSource();
      src.buffer = buffer;
      var filter = c.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(opts.cut || 1400, at);
      var gain = c.createGain();
      gain.gain.setValueAtTime(opts.gain === undefined ? 0.35 : opts.gain, at);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + opts.dur);
      src.connect(filter);
      filter.connect(gain);
      gain.connect(master);
      src.start(at);
    }

    function chord(notes, step, opts) {
      notes.forEach(function (freq, i) {
        tone({
          from: freq,
          to: freq,
          dur: opts && opts.dur ? opts.dur : 0.12,
          type: (opts && opts.type) || "square",
          gain: (opts && opts.gain) || 0.4,
          delay: i * step,
        });
      });
    }

    var EFFECTS = {
      jump: function () {
        tone({ from: 380, to: 760, dur: 0.12, type: "square", gain: 0.35 });
      },
      jump2: function () {
        tone({ from: 520, to: 980, dur: 0.11, type: "square", gain: 0.3 });
      },
      land: function () {
        noise({ dur: 0.07, cut: 700, gain: 0.22 });
      },
      token: function () {
        tone({ from: 988, to: 988, dur: 0.05, type: "square", gain: 0.3 });
        tone({ from: 1319, to: 1319, dur: 0.07, type: "square", gain: 0.26, delay: 0.05 });
      },
      pickup: function () {
        chord([659, 880, 1175], 0.06, { dur: 0.1, type: "triangle", gain: 0.42 });
      },
      stomp: function () {
        tone({ from: 420, to: 110, dur: 0.16, type: "square", gain: 0.4 });
        noise({ dur: 0.1, cut: 900, gain: 0.25 });
      },
      hurt: function () {
        tone({ from: 320, to: 90, dur: 0.28, type: "sawtooth", gain: 0.4 });
      },
      deny: function () {
        tone({ from: 220, to: 180, dur: 0.14, type: "square", gain: 0.34 });
        tone({ from: 165, to: 130, dur: 0.18, type: "square", gain: 0.3, delay: 0.12 });
      },
      blip: function () {
        tone({ from: 760, to: 760, dur: 0.04, type: "square", gain: 0.16 });
      },
      ticket: function () {
        chord([523, 784], 0.07, { dur: 0.12, type: "triangle", gain: 0.36 });
      },
      unlock: function () {
        chord([523, 659, 784, 1047], 0.075, { dur: 0.16, type: "triangle", gain: 0.42 });
      },
      win: function () {
        chord([523, 659, 784, 1047, 1319], 0.09, { dur: 0.22, type: "triangle", gain: 0.45 });
        tone({ from: 1047, to: 1047, dur: 0.5, type: "square", gain: 0.2, delay: 0.45 });
      },
      fail: function () {
        tone({ from: 392, to: 370, dur: 0.18, type: "square", gain: 0.36 });
        tone({ from: 311, to: 294, dur: 0.22, type: "square", gain: 0.34, delay: 0.16 });
        tone({ from: 233, to: 110, dur: 0.5, type: "sawtooth", gain: 0.34, delay: 0.34 });
      },
      bill: function () {
        tone({ from: 160, to: 55, dur: 0.55, type: "sawtooth", gain: 0.42 });
        noise({ dur: 0.3, cut: 500, gain: 0.2 });
      },
      sludge: function () {
        tone({ from: 180, to: 120, dur: 0.22, type: "sawtooth", gain: 0.3 });
        noise({ dur: 0.18, cut: 380, gain: 0.22 });
      },
      vstorm: function () {
        chord([784, 988, 1175, 1568, 1976], 0.06, { dur: 0.3, type: "triangle", gain: 0.4 });
      },
      pause: function () {
        tone({ from: 440, to: 330, dur: 0.1, type: "triangle", gain: 0.25 });
      },
    };

    return {
      get enabled() {
        return on;
      },
      play: function (name) {
        if (!on) return;
        var effect = EFFECTS[name];
        if (!effect) return;
        try {
          effect();
        } catch (err) {
          /* An audio graph that refuses to build is not a reason to stop the
           * game; the run carries on silently. */
        }
      },
      set: function (next) {
        on = !!next;
        try {
          global.localStorage.setItem(SOUND_KEY, on ? "on" : "off");
        } catch (err) {
          /* Unsaved, but honoured for this tab. */
        }
        if (on) wake();
      },
      toggle: function () {
        Sound.set(!on);
        if (on) Sound.play("blip");
        return on;
      },
    };
  })();

  /* The speaker control every page carries, plus M as its shortcut. */
  function soundButton(button) {
    function label() {
      button.textContent = Sound.enabled ? "Sound on" : "Sound off";
      button.setAttribute("aria-pressed", Sound.enabled ? "true" : "false");
    }
    label();
    button.addEventListener("click", function () {
      Sound.toggle();
      label();
    });
    global.document.addEventListener("keydown", function (e) {
      if (e.code === "KeyM" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        Sound.toggle();
        label();
      }
    });
  }

  /* Pause. Three ways in, one way out, and the tab losing focus counts as one
   * of them: a runner whose budget drains while you answer a message elsewhere
   * is a runner that punishes you for leaving, which no arcade cabinet does.
   * `R` restarts without going through the continue screen. */
  function pauser(screen, isPlaying, restart) {
    var panel = global.document.createElement("div");
    panel.className = "arc-paused";
    panel.hidden = true;
    panel.innerHTML = "<h3>Paused</h3><p>P to resume &middot; R to restart</p>";
    screen.appendChild(panel);

    var api = { on: false };

    function set(next) {
      api.on = isPlaying() ? next : false;
      panel.hidden = !api.on;
    }

    global.document.addEventListener("keydown", function (e) {
      if (e.code === "KeyP") {
        if (!isPlaying()) return;
        e.preventDefault();
        set(!api.on);
      } else if (e.code === "KeyR" && restart) {
        e.preventDefault();
        set(false);
        restart();
      }
    });
    global.addEventListener("blur", function () {
      set(true);
    });
    global.document.addEventListener("visibilitychange", function () {
      if (global.document.hidden) set(true);
    });

    return api;
  }

  /* On-screen controls for a touch screen.
   *
   * A phone held upright cannot give a two-to-one canvas more height than half
   * its width, so the bottom half of the page is dead space. This puts the
   * controls there, and it does it by synthesising the same key events the
   * keyboard sends - the games keep one input path, and a thumb and a keyboard
   * are the same thing to them.
   */
  var LAYOUTS = {
    runner: [
      { code: "ArrowDown", label: "Duck" },
      { code: "Space", label: "Jump", main: true },
    ],
    canyon: [
      { code: "ArrowLeft", label: "Left" },
      { code: "ArrowRight", label: "Right" },
      { code: "Space", label: "Jump", main: true },
    ],
    shift: [
      { code: "ArrowLeft", label: "Left" },
      { code: "ArrowUp", label: "Up" },
      { code: "ArrowDown", label: "Down" },
      { code: "ArrowRight", label: "Right" },
      { code: "KeyE", label: "Use", main: true },
    ],
  };

  function touchpad(page, layout) {
    if (!global.matchMedia || !global.matchMedia("(pointer: coarse)").matches) return null;
    var keys = LAYOUTS[layout];
    if (!keys) return null;

    var pad = global.document.createElement("div");
    pad.className = "arc-pad";
    pad.setAttribute("data-layout", layout);
    page.classList.add("has-pad");

    keys.forEach(function (key) {
      var button = global.document.createElement("button");
      button.type = "button";
      button.className = "arc-pad-key" + (key.main ? " is-main" : "");
      button.setAttribute("data-code", key.code);
      button.textContent = key.label;
      button.setAttribute("aria-label", key.label);

      function down(e) {
        e.preventDefault();
        button.classList.add("is-held");
        if (button.setPointerCapture && e.pointerId !== undefined) {
          try {
            button.setPointerCapture(e.pointerId);
          } catch (err) {
            /* Capture is a convenience: without it a finger that slides off the
             * button still releases through the pointerup below. */
          }
        }
        global.document.dispatchEvent(
          new global.KeyboardEvent("keydown", { code: key.code, bubbles: true })
        );
      }

      function up(e) {
        if (e) e.preventDefault();
        if (!button.classList.contains("is-held")) return;
        button.classList.remove("is-held");
        global.document.dispatchEvent(
          new global.KeyboardEvent("keyup", { code: key.code, bubbles: true })
        );
      }

      button.addEventListener("pointerdown", down);
      button.addEventListener("pointerup", up);
      button.addEventListener("pointercancel", up);
      /* A key that is still held when the page goes away is a key that stays
       * held forever. */
      global.addEventListener("blur", function () {
        up(null);
      });

      pad.appendChild(button);
    });

    var legend = page.querySelector(".arc-legend");
    if (legend) page.insertBefore(pad, legend);
    else page.appendChild(pad);
    return pad;
  }

  /* Size the canvas to whatever room the stage has, in CSS pixels, keeping its
   * aspect ratio. The canvas keeps its own small backing resolution - scaling
   * it here is what makes a sixteen-pixel sprite fill a 27-inch screen without
   * the game logic knowing anything about it. */
  function fit(screen, canvas) {
    var stage = screen.parentNode;

    function apply() {
      var box = stage.getBoundingClientRect();
      var frame = 6; /* the cabinet's own border and its shadow */
      var room = { w: box.width - frame, h: box.height - frame };
      if (room.w <= 0 || room.h <= 0) return;
      var scale = Math.min(room.w / canvas.width, room.h / canvas.height);
      if (!isFinite(scale) || scale <= 0) return;
      canvas.style.width = Math.floor(canvas.width * scale) + "px";
      canvas.style.height = Math.floor(canvas.height * scale) + "px";
    }

    apply();
    global.addEventListener("resize", apply);
    global.addEventListener("orientationchange", function () {
      global.setTimeout(apply, 120);
    });
    global.document.addEventListener("fullscreenchange", function () {
      global.setTimeout(apply, 80);
    });
    if (global.ResizeObserver) new global.ResizeObserver(apply).observe(stage);
    return apply;
  }

  /* Real fullscreen on top of the full-window layout: the button and F do the
   * same thing, and the label follows the actual state rather than a flag of
   * our own - leaving fullscreen with Escape never reaches the button. */
  function fullscreen(page, button) {
    function supported() {
      return !!(page.requestFullscreen || page.webkitRequestFullscreen);
    }
    if (!supported()) {
      button.hidden = true;
      return;
    }

    function toggle() {
      if (global.document.fullscreenElement) {
        global.document.exitFullscreen();
      } else if (page.requestFullscreen) {
        page.requestFullscreen().catch(function () {
          /* Refused by the browser - the windowed layout is already full-page,
           * so there is nothing to recover from. */
        });
      } else {
        page.webkitRequestFullscreen();
      }
    }

    button.addEventListener("click", toggle);
    global.document.addEventListener("keydown", function (e) {
      if (e.code === "KeyF" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        toggle();
      }
    });
    global.document.addEventListener("fullscreenchange", function () {
      button.textContent = global.document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
    });
  }

  /* A fixed 60Hz step, so a 120Hz screen does not run the game at double speed
   * and a background tab does not spiral when it comes back. */
  function loop(update, draw) {
    var acc = 0;
    var last = global.performance.now();
    function frame(now) {
      acc += Math.min(80, now - last);
      last = now;
      while (acc >= 1000 / 60) {
        update();
        acc -= 1000 / 60;
      }
      draw();
      global.requestAnimationFrame(frame);
    }
    global.requestAnimationFrame(frame);
  }

  global.Amigo = {
    harness: Harness,
    parts: PARTS,
    kinds: KINDS,
    repo: REPO,
    sprites: sprites,
    toast: toast,
    unlockToast: unlockToast,
    continueScreen: continueScreen,
    wireContinue: wireContinue,
    loop: loop,
    fit: fit,
    fullscreen: fullscreen,
    pauser: pauser,
    touchpad: touchpad,
    sound: Sound,
    soundButton: soundButton,
  };
})(window);
