(function () {
  "use strict";
  var E = window.ArcadeEngines,
    A = window.Amigo,
    H = A.harness;
  var isContext =
    document.querySelector("[data-cabinet]").dataset.cabinet === "context";
  var $ = function (id) {
    return document.getElementById(id);
  };
  var canvas = $("game"),
    g = canvas.getContext("2d"),
    sprites = A.sprites();
  var overlay = $("overlay"),
    running = false,
    paused = false,
    finished = false,
    state;
  var provider = "anthropic";
  var partByType = {
    tool: "tool.web_search",
    mcp: "mcp.github",
    skill: "skill.compaction",
  };
  var last = performance.now(),
    visualTime = 0,
    summary = "";
  var colors = {
    instruction: "#eac05c",
    document: "#54b6ce",
    memory: "#b587d5",
    noise: "#687084",
    tool: "#70c99b",
    mcp: "#819af3",
    skill: "#ef9670",
  };
  var letters = {
    instruction: "I",
    document: "D",
    memory: "M",
    noise: "×",
    tool: "T",
    mcp: "↔",
    skill: "S",
  };
  var names = {
    instruction: "AGENTS.md",
    document: "Docs / RAG",
    memory: "Memory",
    noise: "Verbose logs",
    tool: "Web search",
    mcp: "GitHub MCP",
    skill: "Compaction",
  };
  g.imageSmoothingEnabled = false;
  function put(id, text) {
    if ($(id).textContent !== String(text)) $(id).textContent = text;
  }
  function unlock(id) {
    var part = H.unlock(id);
    if (part) A.unlockToast($("screen"), part);
  }
  function fresh() {
    state = isContext
      ? E.context({ filter: H.has("data.signal_filter"), provider: provider })
      : E.office({
          efficient: H.has("skill.coordination"),
          provider: provider,
          gear: Object.fromEntries(
            Object.entries(E.GEAR).map(function (entry) {
              return [entry[0], H.has(entry[1].part)];
            }),
          ),
        });
    sprites = A.sprites();
  }
  function best() {
    var stats = H.stats();
    put(
      "best",
      isContext
        ? "Personal best: " + stats.contextBest + " points"
        : "Best delivery: " +
            stats.agentsBest +
            " points · " +
            stats.agentsWins +
            " shipped",
    );
  }
  function start() {
    fresh();
    running = true;
    finished = false;
    paused = false;
    overlay.hidden = true;
    $("paused").hidden = true;
    $("pause").disabled = false;
    $("pause").textContent = "Pause";
    H.played(isContext ? "context" : "agents");
    document.activeElement.blur();
    updateUI();
  }
  function pause(value) {
    if (!running || finished) return;
    paused = value;
    $("paused").hidden = !paused;
    $("pause").textContent = paused ? "Resume" : "Pause";
    if (paused) $("resume").focus();
    else document.activeElement.blur();
    updateUI();
  }
  function finish() {
    if (finished) return;
    if (state.status === "won" || (isContext && state.tasks > 0)) {
      unlock(
        {
          openai: "model.gpt",
          anthropic: "model.claude",
          qwen: "model.qwen",
          deepseek: "model.deepseek",
        }[provider],
      );
    }
    finished = true;
    running = false;
    $("pause").disabled = true;
    if (isContext) {
      H.record({
        contextBest: { best: state.score },
        contextRuns: { add: 1 },
        contextTasks: { add: state.tasks },
      });
      if (state.tasks >= 1) unlock("data.signal_filter");
      summary =
        "Context Tetris: " +
        state.score +
        " points, " +
        state.lines +
        " rows, " +
        state.tasks +
        " tasks answered.\nMy context window is full. My confidence is not.";
    } else {
      H.record({
        agentsBest: { best: state.score },
        agentsRuns: { add: 1 },
        agentsWins: { add: state.status === "won" ? 1 : 0 },
      });
      if (state.status === "won") unlock("skill.coordination");
      summary =
        "Just One More Agent: " +
        state.peak +
        " agents, $" +
        state.spent.toFixed(2) +
        ", " +
        Math.floor(state.progress) +
        "% done.\n" +
        (state.status === "won"
          ? "One comma shipped. " + state.score + " points."
          : "The comma is still in review.");
    }
    overlay.replaceChildren();
    var eyebrow = document.createElement("p");
    eyebrow.className = "arc-reason";
    eyebrow.textContent = isContext
      ? "Context window exceeded"
      : state.status === "won"
        ? "Ticket closed. Finally."
        : "The invoice has arrived.";
    var title = document.createElement("h2");
    title.textContent = isContext
      ? "Out of context."
      : state.status === "won"
        ? "One comma. Shipped."
        : "One agent too many?";
    if (state.status === "won") title.className = "is-win";
    var result = document.createElement("p");
    result.className = "result-text";
    result.textContent = summary;
    var actions = document.createElement("div");
    actions.className = "arc-actions";
    var retry = document.createElement("button");
    retry.className = "arc-btn is-primary";
    retry.textContent = "Try again";
    retry.dataset.action = "retry";
    var copy = document.createElement("button");
    copy.className = "arc-btn";
    copy.textContent = "Copy result";
    copy.dataset.action = "copy";
    actions.append(retry, copy);
    var status = document.createElement("p");
    status.id = "copyStatus";
    status.className = "arc-hint copy-status";
    status.setAttribute("role", "status");
    var back = document.createElement("a");
    back.href = "./";
    back.className = "arc-back";
    back.textContent = "← Your harness & the arcade";
    overlay.append(eyebrow, title, result, actions, status, back);
    overlay.hidden = false;
    retry.focus();
    best();
  }
  overlay.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (b.id === "start" || b.dataset.action === "retry") start();
    if (b.dataset.action === "copy") {
      var text = summary + "\n" + location.href.split(/[?#]/)[0];
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () {
            put("copyStatus", "Copied. Challenge someone to beat it.");
          },
          function () {
            put(
              "copyStatus",
              "Copy unavailable — select the result text above.",
            );
          },
        );
      } else
        put("copyStatus", "Copy unavailable — select the result text above.");
    }
  });
  A.fullscreen(document.querySelector("main"), $("fs"));
  A.soundButton($("sound"));
  document.querySelectorAll("[data-provider]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (running) return;
      provider = button.dataset.provider;
      fresh();
      updateUI();
      draw();
    });
  });
  document.querySelectorAll("[data-gear]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!running || paused || finished) return;
      if (E.equip(state, button.dataset.gear)) {
        unlock(E.GEAR[button.dataset.gear].part);
        A.sound.play("unlock");
        updateUI();
        draw();
      }
    });
  });
  // Fit each canvas to its own remaining playfield, including browser fullscreen.
  function fitBoard() {
    var field = canvas.parentElement;
    var scale = Math.max(
      0.05,
      Math.min(
        (field.clientWidth - 12) / canvas.width,
        (field.clientHeight - 12) / canvas.height,
      ),
    );
    canvas.style.width = Math.floor(canvas.width * scale) + "px";
    canvas.style.height = Math.floor(canvas.height * scale) + "px";
  }
  new ResizeObserver(fitBoard).observe(canvas.parentElement);
  window.addEventListener("resize", fitBoard);
  $("pause").addEventListener("click", function () {
    pause(!paused);
  });
  $("resume").addEventListener("click", function () {
    pause(false);
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) pause(true);
  });
  window.addEventListener("blur", function () {
    pause(true);
  });
  function action(name) {
    if (!running || paused || finished) return;
    if (isContext) {
      if (name === "left") E.move(state, -1, 0);
      if (name === "right") E.move(state, 1, 0);
      if (name === "down" && E.move(state, 0, 1)) state.score++;
      if (name === "rotate") E.rotate(state);
      if (name === "drop") E.hardDrop(state);
      if (name === "discard") E.discard(state);
      if (state.tasks >= 1) unlock("data.signal_filter");
    } else {
      if (name === "hire") E.hire(state);
      if (name === "dismiss") E.dismiss(state);
      if (name === "focus") E.focus(state);
    }
    collectBonuses();
    if (state.status !== "playing") finish();
    A.sound.play("blip");
    updateUI();
    draw();
  }
  if (isContext) {
    document.querySelectorAll("[data-control]").forEach(function (b) {
      b.addEventListener("click", function () {
        action(b.dataset.control);
      });
    });
    $("discard").addEventListener("click", function () {
      action("discard");
    });
    var touch = null;
    canvas.addEventListener("pointerdown", function (e) {
      touch = { x: e.clientX, y: e.clientY };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointerup", function (e) {
      if (!touch) return;
      var dx = e.clientX - touch.x,
        dy = e.clientY - touch.y;
      touch = null;
      if (Math.abs(dx) < 15 && Math.abs(dy) < 15) action("rotate");
      else if (Math.abs(dx) > Math.abs(dy)) action(dx > 0 ? "right" : "left");
      else action(dy > 0 ? "drop" : "rotate");
    });
    canvas.addEventListener("pointercancel", function () {
      touch = null;
    });
  } else
    ["hire", "dismiss", "focus"].forEach(function (id) {
      $(id).addEventListener("click", function () {
        action(id);
      });
    });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (
      (e.code === "Space" || e.code === "Enter") &&
      e.target.closest("button,a")
    )
      return;
    if (e.code === "KeyP" || e.code === "Escape") {
      e.preventDefault();
      if (!e.repeat) pause(!paused);
      return;
    }
    if (e.code === "KeyR") {
      e.preventDefault();
      if (!e.repeat) start();
      return;
    }
    if (!running && e.code === "Space") {
      e.preventDefault();
      if (!e.repeat) start();
      return;
    }
    var map = isContext
      ? {
          ArrowLeft: "left",
          ArrowRight: "right",
          ArrowUp: "rotate",
          ArrowDown: "down",
          Space: "drop",
          KeyX: "discard",
        }
      : { KeyH: "hire", KeyD: "dismiss", KeyC: "focus" };
    if (map[e.code]) {
      e.preventDefault();
      if (!e.repeat || ["left", "right", "down"].includes(map[e.code]))
        action(map[e.code]);
    }
  });
  function collectBonuses() {
    if (isContext)
      state.activated.forEach(function (type) {
        unlock(partByType[type]);
      });
  }
  function updateUI() {
    put("message", state.message);
    put(
      "providerPerk",
      E.PROVIDERS[provider].perk
        .split(" · ")
        [isContext ? 1 : 0].replace(/^Tetris /, ""),
    );
    document.querySelectorAll("[data-provider]").forEach(function (button) {
      button.disabled = running;
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.provider === provider),
      );
    });
    put(
      "activeLoadout",
      E.PROVIDERS[provider].name +
        " · " +
        (isContext
          ? state.slow > 0
            ? "COMPACTION " + Math.ceil(state.slow) + "s"
            : "I / D / M → answers · T / MCP / S → bonuses"
          : Object.keys(state.gear)
              .filter(function (k) {
                return state.gear[k];
              })
              .map(function (k) {
                return E.GEAR[k].name;
              })
              .join(" + ") || "base agent"),
    );
    var disabled = !running || paused || finished;
    if (isContext) {
      put("score", state.score);
      put("lines", state.lines);
      put("tasks", state.tasks);
      E.taskProgress(state).forEach(function (p) {
        put(
          "task" + p.type[0].toUpperCase() + p.type.slice(1),
          " · " + letters[p.type] + " " + p.have + "/" + p.need,
        );
      });
      ["instruction", "document", "memory", "tool", "mcp", "skill"].forEach(
        function (type) {
          put(type, state.collected[type] + " / 4");
        },
      );
      put("nextName", names[state.next.type]);
      put("currentName", "Falling: " + names[state.piece.type]);
      put("discard", "Discard · " + state.erasers + " left [X]");
      $("discard").disabled = disabled || !state.erasers;
      document.querySelectorAll("[data-control]").forEach(function (b) {
        b.disabled =
          disabled || (b.dataset.control === "discard" && !state.erasers);
        if (b.dataset.control === "discard")
          b.textContent = "X · " + state.erasers;
      });
    } else {
      document.querySelectorAll("[data-gear]").forEach(function (button) {
        var key = button.dataset.gear,
          equipped = state.gear[key];
        button.disabled =
          disabled || equipped || state.budget < E.GEAR[key].cost;
        button.classList.toggle("is-equipped", equipped);
        button.querySelector("small").textContent = equipped
          ? "CONNECTED · " + E.GEAR[key].effect
          : "$" + E.GEAR[key].cost + " · " + E.GEAR[key].effect;
      });
      put("budget", "$" + state.budget.toFixed(0));
      put("agents", state.agents);
      put("clock", Math.max(0, Math.ceil(90 - state.time)) + "s");
      put("progress", Math.floor(state.progress) + "%");
      $("progressFill").style.width = state.progress + "%";
      put("chaos", Math.round(state.chaos) + "%");
      $("chaosFill").style.width = state.chaos + "%";
      put("rate", E.officeRate(state).toFixed(1) + "% of the task / second");
      put(
        "meeting",
        state.focus > 0
          ? "Focus sprint: " + Math.ceil(state.focus) + "s left."
          : state.meeting > 0
            ? "In a meeting. " + Math.ceil(state.meeting) + "s of alignment."
            : "No meetings. Enjoy it.",
      );
      put(
        "focus",
        state.cooldown > 0
          ? "Focus recharging · " + Math.ceil(state.cooldown) + "s"
          : "Focus · $15 [C]",
      );
      $("hire").disabled = disabled || state.budget < 12 || state.agents >= 32;
      $("dismiss").disabled = disabled || state.agents <= 1;
      $("focus").disabled = disabled || state.cooldown > 0 || state.budget < 15;
    }
  }
  function block(ctx, x, y, size, type, ghost) {
    ctx.globalAlpha = ghost ? 0.23 : 1;
    ctx.fillStyle = colors[type];
    ctx.fillRect(x + 1, y + 1, size - 2, size - 2);
    ctx.fillStyle = "rgba(255,255,255,.25)";
    ctx.fillRect(x + 2, y + 2, size - 4, 2);
    ctx.fillStyle = "#131722";
    ctx.font = "bold " + Math.floor(size * 0.43) + "px monospace";
    ctx.textAlign = "center";
    ctx.fillText(letters[type], x + size / 2, y + size * 0.68);
    ctx.globalAlpha = 1;
  }
  function drawContext() {
    g.fillStyle = "#0e111b";
    g.fillRect(0, 0, 300, 540);
    g.strokeStyle = "#1c2231";
    g.lineWidth = 1;
    for (var x = 0; x <= 10; x++) {
      g.beginPath();
      g.moveTo(x * 30, 0);
      g.lineTo(x * 30, 540);
      g.stroke();
    }
    for (var y = 0; y <= 18; y++) {
      g.beginPath();
      g.moveTo(0, y * 30);
      g.lineTo(300, y * 30);
      g.stroke();
    }
    state.board.forEach(function (row, y) {
      row.forEach(function (type, x) {
        if (type) block(g, x * 30, y * 30, 30, type);
      });
    });
    var p = state.piece,
      gy = p.y;
    while (E.fits(state, p.cells, p.x, gy + 1)) gy++;
    p.cells.forEach(function (c) {
      block(g, (p.x + c[0]) * 30, (gy + c[1]) * 30, 30, p.type, true);
    });
    p.cells.forEach(function (c) {
      block(g, (p.x + c[0]) * 30, (p.y + c[1]) * 30, 30, p.type);
    });
    var ng = $("next").getContext("2d");
    ng.clearRect(0, 0, 96, 64);
    state.next.cells.forEach(function (c) {
      block(ng, 8 + c[0] * 20, 12 + c[1] * 20, 20, state.next.type);
    });
  }
  function drawOffice() {
    var w = 640,
      h = 400;
    g.fillStyle = "#171522";
    g.fillRect(0, 0, w, h);
    g.fillStyle = "#29253b";
    g.fillRect(0, 0, w, 73);
    // Sunset windows frame the same little mascot as the original cabinets.
    for (var i = 0; i < 5; i++) {
      var wx = 28 + i * 128;
      g.fillStyle = "#12121e";
      g.fillRect(wx, 13, 73, 46);
      g.fillStyle = "#693450";
      g.fillRect(wx + 3, 16, 67, 40);
      g.fillStyle = "#bb6654";
      g.fillRect(wx + 3, 39, 67, 17);
      g.fillStyle = "#efb95b";
      g.fillRect(wx + 45, 24, 12, 12);
      g.fillStyle = "#28273b";
      g.fillRect(wx + 35, 16, 3, 40);
    }
    for (var yy = 76; yy < h; yy += 26) {
      g.strokeStyle = "#242334";
      g.beginPath();
      g.moveTo(0, yy);
      g.lineTo(w, yy);
      g.stroke();
    }
    for (var xx = 0; xx < w; xx += 40) {
      g.strokeStyle = "#222131";
      g.beginPath();
      g.moveTo(xx, 73);
      g.lineTo(xx, h);
      g.stroke();
    }
    var positions = [];
    for (var n = 0; n < state.agents; n++)
      positions.push({ x: 35 + (n % 8) * 78, y: 104 + Math.floor(n / 8) * 54 });
    if (state.agents > 1) {
      g.strokeStyle = state.meeting > 0 ? "#a26c4a" : "#42354c";
      g.lineWidth = 1;
      positions.forEach(function (p, i) {
        for (var j = i + 1; j < positions.length; j++) {
          if ((i + j) % 3 && state.chaos < 50) continue;
          g.beginPath();
          g.moveTo(p.x + 15, p.y + 14);
          g.lineTo(positions[j].x + 15, positions[j].y + 14);
          g.stroke();
        }
      });
    }
    positions.forEach(function (p, i) {
      var frame =
        Math.floor(visualTime * 3 + i) % 2 ? sprites.stand : sprites.step;
      g.fillStyle = "#0e1018";
      g.fillRect(p.x - 6, p.y + 29, 48, 6);
      g.drawImage(frame, p.x, p.y - 13, 32, 38);
      g.fillStyle = "#544357";
      g.fillRect(p.x - 6, p.y + 21, 48, 9);
      g.fillStyle = "#202636";
      g.fillRect(p.x + 17, p.y + 5, 22, 17);
      g.fillStyle =
        state.meeting > 0 ? "#df9f60" : state.focus > 0 ? "#91cca7" : "#61abc4";
      g.fillRect(p.x + 19, p.y + 7, 18, 12);
      g.fillStyle = "#15202c";
      g.fillRect(p.x + 21, p.y + 10, 10, 2);
      g.fillRect(p.x + 21, p.y + 14, 6, 2);
      if (state.meeting > 0 && i % 2 === 0) {
        g.fillStyle = "#eac05c";
        g.fillRect(p.x + 2, p.y - 23, 25, 10);
        g.fillStyle = "#262238";
        g.font = "9px monospace";
        g.textAlign = "center";
        g.fillText("...", p.x + 14, p.y - 16);
      }
    });
    g.fillStyle = "#11131e";
    g.fillRect(0, 302, 640, 28);
    g.fillStyle = state.meeting > 0 ? "#eac05c" : "#99a0ad";
    g.font = "11px monospace";
    g.textAlign = "left";
    g.fillText(
      state.meeting > 0
        ? "ALL HANDS: LET’S ALIGN ON THE COMMA"
        : state.focus > 0
          ? "FOCUS MODE: PLEASE DO THE ACTUAL TASK"
          : 'TICKET #001: REPLACE ";" WITH ","',
      18,
      320,
    );
    Object.keys(E.GEAR).forEach(function (key, i) {
      var x = 16 + i * 156,
        on = state.gear[key];
      g.fillStyle = on ? "#1c392f" : "#222336";
      g.fillRect(x, 340, 144, 48);
      g.strokeStyle = on ? "#70c99b" : "#3b3c50";
      g.strokeRect(x + 0.5, 340.5, 144, 48);
      g.fillStyle = on ? "#70c99b" : "#777e94";
      g.font = "10px monospace";
      g.textAlign = "left";
      g.fillText(E.GEAR[key].name, x + 9, 358);
      g.fillStyle = on ? "#b6e8be" : "#687084";
      g.font = "9px monospace";
      g.fillText(on ? "CONNECTED" : "EMPTY SLOT", x + 9, 378);
      if (on && running && !paused) {
        g.fillStyle = "#a5edbe";
        g.fillRect(x + 126, 350 + (Math.floor(visualTime * 3) % 3) * 8, 4, 4);
      }
    });
  }
  function draw() {
    if (isContext) drawContext();
    else drawOffice();
  }
  fresh();
  fitBoard();
  best();
  updateUI();
  $("perkLine").textContent = isContext
    ? H.has("data.signal_filter")
      ? "Harness active: signal filter gives one extra discard."
      : "Answer a task to unlock Signal filter for your harness."
    : H.has("skill.coordination")
      ? "Harness active: coordination cuts running costs by 10%."
      : "Ship the comma to unlock Coordination for your harness.";
  function frame(now) {
    var dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    if (running && !paused && !finished) {
      visualTime += dt;
      if (isContext) E.contextStep(state, dt);
      else E.officeStep(state, dt);
      if (isContext && state.tasks >= 1) unlock("data.signal_filter");
      collectBonuses();
      if (state.status !== "playing") finish();
      updateUI();
    }
    draw();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
