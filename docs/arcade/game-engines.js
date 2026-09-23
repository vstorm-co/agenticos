/* Pure rules shared by the cabinets and their deterministic tests. No network. */
(function (root) {
  "use strict";
  // These are game modifiers, not real-world provider benchmarks or pricing.
  var PROVIDERS = {
    openai: {
      name: "OpenAI",
      speed: 1.12,
      cost: 1.12,
      chaos: 1,
      drop: 1,
      points: 1.2,
      perk: "+12% work / +12% bill · Tetris +20% points",
    },
    anthropic: {
      name: "Anthropic",
      speed: 1,
      cost: 1.05,
      chaos: 0.75,
      drop: 1.18,
      points: 1,
      perk: "−25% chaos · Tetris falls 18% slower",
    },
    qwen: {
      name: "Qwen",
      speed: 0.9,
      cost: 0.72,
      chaos: 1,
      drop: 1,
      points: 1,
      perk: "−28% bill / −10% work · Tetris +1 discard",
    },
    deepseek: {
      name: "DeepSeek",
      speed: 1,
      cost: 0.88,
      chaos: 1.15,
      drop: 0.9,
      points: 1.35,
      perk: "−12% bill / +15% chaos · faster Tetris, +35% points",
    },
  };
  var GEAR = {
    tool: {
      name: "Web search",
      cost: 18,
      part: "tool.web_search",
      effect: "+15% work speed",
    },
    mcp: {
      name: "GitHub MCP",
      cost: 25,
      part: "mcp.github",
      effect: "+10% work; focus recharges faster",
    },
    docs: {
      name: "Company docs",
      cost: 16,
      part: "context.playbook",
      effect: "−15 chaos; calmer team",
    },
    skill: {
      name: "Delegation skill",
      cost: 22,
      part: "skill.handoff",
      effect: "−35% coordination growth",
    },
  };
  function equip(s, key) {
    var item = GEAR[key];
    if (!item || s.status !== "playing" || s.gear[key] || s.budget < item.cost)
      return false;
    s.budget -= item.cost;
    s.spent += item.cost;
    s.gear[key] = true;
    if (key === "docs") s.chaos = Math.max(0, s.chaos - 15);
    s.message = item.name + " connected. " + item.effect + ".";
    return true;
  }
  function office(options) {
    options = options || {};
    return {
      provider: PROVIDERS[options.provider] ? options.provider : "anthropic",
      gear: Object.assign(
        { tool: false, mcp: false, docs: false, skill: false },
        options.gear,
      ),
      agents: 1,
      peak: 1,
      budget: 300,
      spent: 0,
      progress: 0,
      chaos: 0,
      time: 0,
      meeting: 0,
      focus: 0,
      cooldown: 0,
      nextEvent: 10,
      events: 0,
      status: "playing",
      efficient: !!options.efficient,
      score: 0,
      message: "One comma. How many agents could it take?",
    };
  }
  function hire(s) {
    if (s.status !== "playing" || s.budget < 12 || s.agents >= 32) return false;
    s.budget -= 12;
    s.spent += 12;
    s.agents++;
    s.peak = Math.max(s.peak, s.agents);
    s.chaos = Math.min(100, s.chaos + 6);
    s.message =
      s.agents > 6
        ? "The new agent has requested an onboarding agent."
        : "Agent hired. Another opinion has entered the chat.";
    return true;
  }
  function dismiss(s) {
    if (s.status !== "playing" || s.agents <= 1) return false;
    s.agents--;
    s.chaos = Math.max(0, s.chaos - 8);
    s.message = "One fewer agent. One fewer alignment meeting.";
    return true;
  }
  function focus(s) {
    if (s.status !== "playing" || s.cooldown > 0 || s.budget < 15) return false;
    s.budget -= 15;
    s.spent += 15;
    s.chaos = Math.max(0, s.chaos - 28);
    s.meeting = 0;
    s.focus = 5;
    s.cooldown = s.gear.mcp ? 9 : 12;
    s.message = "Meetings cancelled. Five seconds of actual work.";
    return true;
  }
  function officeRate(s) {
    return (
      Math.max(0.12, s.agents * 0.92 * (1 - s.chaos / 115)) *
      (s.meeting > 0 ? 0.12 : 1) *
      (s.focus > 0 ? 1.5 : 1) *
      PROVIDERS[s.provider].speed *
      (s.gear.tool ? 1.15 : 1) *
      (s.gear.mcp ? 1.1 : 1)
    );
  }
  function officeStep(s, dt) {
    if (s.status !== "playing") return;
    s.time += dt;
    s.cooldown = Math.max(0, s.cooldown - dt);
    s.focus = Math.max(0, s.focus - dt);
    s.meeting = Math.max(0, s.meeting - dt);
    s.chaos = Math.max(
      0,
      Math.min(
        100,
        s.chaos +
          (s.agents *
            (s.agents - 1) *
            0.16 *
            PROVIDERS[s.provider].chaos *
            (s.gear.skill ? 0.65 : 1) -
            (s.gear.docs ? 1.1 : 0.65)) *
            dt,
      ),
    );
    var cost =
      (0.65 + s.agents * 0.65 + s.chaos * 0.026) *
      (s.efficient ? 0.9 : 1) *
      PROVIDERS[s.provider].cost *
      dt;
    s.spent += Math.min(s.budget, cost);
    s.budget = Math.max(0, s.budget - cost);
    s.progress = Math.min(100, s.progress + officeRate(s) * dt);
    if (s.time >= s.nextEvent) {
      s.nextEvent += 10;
      s.events++;
      if (s.agents >= 5) {
        s.meeting = 3 + Math.min(5, s.agents / 3);
        s.message = [
          "A stand-up to discuss yesterday's stand-up.",
          "The agents formed a committee to name the comma.",
          "Two agents are reviewing each other's reviews.",
        ][s.events % 3];
      } else
        s.message = [
          "The comma now has acceptance criteria.",
          "No meeting invite. Suspiciously productive.",
          "Someone asked whether the comma should be a microservice.",
        ][s.events % 3];
    }
    if (s.progress >= 100) {
      s.status = "won";
      s.score = Math.round(s.budget * 10 + Math.max(0, 90 - s.time) * 20);
      s.message = "One comma shipped. Civilization can continue.";
    } else if (s.budget <= 0 || s.time >= 90) {
      s.status = "lost";
      s.message =
        s.budget <= 0
          ? "The budget is gone. The comma is still in review."
          : "Deadline reached. The agents would like an extension.";
    }
  }

  var SHAPES = [
    [
      [0, 0],
      [1, 0],
      [2, 0],
      [3, 0],
    ],
    [
      [0, 0],
      [1, 0],
      [0, 1],
      [1, 1],
    ],
    [
      [1, 0],
      [0, 1],
      [1, 1],
      [2, 1],
    ],
    [
      [0, 0],
      [0, 1],
      [1, 1],
      [2, 1],
    ],
    [
      [2, 0],
      [0, 1],
      [1, 1],
      [2, 1],
    ],
    [
      [1, 0],
      [2, 0],
      [0, 1],
      [1, 1],
    ],
    [
      [0, 0],
      [1, 0],
      [1, 1],
      [2, 1],
    ],
  ];
  var TYPES = [
    "instruction",
    "document",
    "memory",
    "noise",
    "tool",
    "mcp",
    "skill",
  ];
  function context(options) {
    options = options || {};
    var s = {
      board: Array.from({ length: 18 }, function () {
        return Array(10).fill(null);
      }),
      provider: PROVIDERS[options.provider] ? options.provider : "anthropic",
      activated: [],
      slow: 0,
      piece: null,
      next: null,
      bag: [],
      random: options.random || Math.random,
      status: "playing",
      score: 0,
      lines: 0,
      tasks: 0,
      discarded: 0,
      collected: {
        instruction: 0,
        document: 0,
        memory: 0,
        tool: 0,
        mcp: 0,
        skill: 0,
      },
      erasers: (options.filter ? 4 : 3) + (options.provider === "qwen" ? 1 : 0),
      locks: 0,
      dropClock: 0,
      message: "Clear rows to bank the useful context. Keep the noise out.",
    };
    s.next = nextPiece(s);
    spawn(s);
    return s;
  }
  function nextPiece(s) {
    if (!s.bag.length) {
      s.bag = [0, 1, 2, 3, 4, 5, 6];
      for (var i = 6; i > 0; i--) {
        var j = Math.floor(s.random() * (i + 1));
        var a = s.bag[i];
        s.bag[i] = s.bag[j];
        s.bag[j] = a;
      }
    }
    return {
      cells: SHAPES[s.bag.pop()].map(function (p) {
        return p.slice();
      }),
      type: TYPES[Math.floor(s.random() * TYPES.length)],
      x: 3,
      y: 0,
    };
  }
  function fits(s, cells, x, y) {
    return cells.every(function (p) {
      var xx = x + p[0],
        yy = y + p[1];
      return xx >= 0 && xx < 10 && yy >= 0 && yy < 18 && !s.board[yy][xx];
    });
  }
  function spawn(s) {
    s.piece = s.next;
    s.next = nextPiece(s);
    s.dropClock = 0;
    if (!fits(s, s.piece.cells, s.piece.x, s.piece.y)) {
      s.status = "lost";
      s.message = "Context window exceeded. You forgot what you were doing.";
    }
  }
  function move(s, dx, dy) {
    if (s.status !== "playing") return false;
    if (!fits(s, s.piece.cells, s.piece.x + dx, s.piece.y + dy)) return false;
    s.piece.x += dx;
    s.piece.y += dy;
    return true;
  }
  function rotate(s) {
    if (s.status !== "playing") return false;
    var cells = s.piece.cells.map(function (p) {
      return [-p[1], p[0]];
    });
    var minX = Math.min.apply(
      null,
      cells.map(function (p) {
        return p[0];
      }),
    );
    var minY = Math.min.apply(
      null,
      cells.map(function (p) {
        return p[1];
      }),
    );
    cells = cells.map(function (p) {
      return [p[0] - minX, p[1] - minY];
    });
    for (var kick of [0, -1, 1, -2, 2]) {
      if (fits(s, cells, s.piece.x + kick, s.piece.y)) {
        s.piece.cells = cells;
        s.piece.x += kick;
        return true;
      }
    }
    return false;
  }
  function clearRows(s) {
    var count = 0;
    s.board = s.board.filter(function (row) {
      if (!row.every(Boolean)) return true;
      count++;
      row.forEach(function (type) {
        if (type !== "noise") {
          s.collected[type]++;
          s.score += Math.round(15 * PROVIDERS[s.provider].points);
        }
      });
      return false;
    });
    while (s.board.length < 18) s.board.unshift(Array(10).fill(null));
    if (count) {
      s.lines += count;
      s.score += [0, 100, 300, 500, 800][count];
      s.message =
        count +
        " row" +
        (count > 1 ? "s" : "") +
        " compacted. Useful context banked.";
      while (
        s.collected.instruction >= 4 &&
        s.collected.document >= 4 &&
        s.collected.memory >= 4
      ) {
        TYPES.slice(0, 3).forEach(function (t) {
          s.collected[t] -= 4;
        });
        s.tasks++;
        s.score += 600;
        s.erasers = Math.min(5, s.erasers + 1);
        s.message = "Task answered! +600 points and one discard restored.";
      }
    }
    ["tool", "mcp", "skill"].forEach(function (type) {
      while (s.collected[type] >= 4) {
        s.collected[type] -= 4;
        if (!s.activated.includes(type)) s.activated.push(type);
        if (type === "tool") {
          s.score += 250;
          s.message = "Web search found the source. +250 points.";
        }
        if (type === "mcp") {
          s.erasers = Math.min(5, s.erasers + 1);
          s.message = "GitHub MCP connected. One discard restored.";
        }
        if (type === "skill") {
          s.slow = 15;
          s.message =
            "Compaction skill activated. Slower blocks for 15 seconds.";
        }
      }
    });
    return count;
  }
  function lock(s) {
    if (s.status !== "playing") return;
    s.piece.cells.forEach(function (p) {
      s.board[s.piece.y + p[1]][s.piece.x + p[0]] = s.piece.type;
    });
    s.locks++;
    clearRows(s);
    spawn(s);
  }
  function hardDrop(s) {
    if (s.status !== "playing") return;
    while (move(s, 0, 1)) s.score += 2;
    lock(s);
  }
  function discard(s) {
    if (s.status !== "playing" || !s.erasers) return false;
    s.erasers--;
    s.discarded++;
    s.message =
      s.piece.type === "noise"
        ? "Verbose logs evicted. Nothing of value was lost."
        : "Useful context discarded. Hope you remember that later.";
    spawn(s);
    return true;
  }
  function contextStep(s, dt) {
    if (s.status !== "playing") return;
    s.slow = Math.max(0, s.slow - dt);
    s.dropClock += dt;
    var interval =
      Math.max(0.16, 0.85 - Math.floor(s.lines / 4) * 0.075) *
      PROVIDERS[s.provider].drop *
      (s.slow > 0 ? 1.5 : 1);
    if (s.dropClock >= interval) {
      s.dropClock = 0;
      if (!move(s, 0, 1)) lock(s);
    }
  }
  var api = {
    PROVIDERS,
    GEAR,
    equip,
    office,
    hire,
    dismiss,
    focus,
    officeRate,
    officeStep,
    context,
    fits,
    move,
    rotate,
    clearRows,
    lock,
    hardDrop,
    discard,
    contextStep,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ArcadeEngines = api;
})(typeof window !== "undefined" ? window : globalThis);
