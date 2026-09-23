// Run with: node --test scripts/test_arcade.cjs
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const E = require("../docs/arcade/game-engines.js");
const root = path.join(__dirname, "../docs/arcade");
const advance = (s) => {
  for (let n = 0; n < 6000 && s.status === "playing"; n++)
    E.officeStep(s, 1 / 60);
  return s;
};

test("small team can ship; unattended solo run misses its deadline", () => {
  const solo = advance(E.office());
  assert.equal(solo.status, "lost");
  assert.ok(solo.progress < 100);
  const team = E.office();
  E.hire(team);
  E.hire(team);
  advance(team);
  assert.equal(team.status, "won");
  assert.ok(team.budget > 0);
  assert.ok(team.score > 0);
});
test("over-hiring loses to budget, and finished runs cannot mutate", () => {
  const s = E.office();
  for (let i = 0; i < 12; i++) E.hire(s);
  advance(s);
  assert.equal(s.status, "lost");
  assert.equal(s.budget, 0);
  const before = JSON.stringify(s);
  E.officeStep(s, 100);
  E.hire(s);
  E.dismiss(s);
  E.focus(s);
  assert.equal(JSON.stringify(s), before);
});
test("focus cancels meetings, costs money, and respects cooldown", () => {
  const s = E.office();
  for (let i = 0; i < 5; i++) E.hire(s);
  E.officeStep(s, 10);
  assert.ok(s.meeting > 0);
  const before = s.budget;
  assert.equal(E.focus(s), true);
  assert.equal(s.meeting, 0);
  assert.equal(s.budget, before - 15);
  assert.equal(E.focus(s), false);
  E.officeStep(s, 12);
  assert.equal(s.cooldown, 0);
});
test("earned coordination reduces costs", () => {
  const a = E.office(),
    b = E.office({ efficient: true });
  E.officeStep(a, 10);
  E.officeStep(b, 10);
  assert.ok(b.budget > a.budget);
});
test("blocks stay in bounds; wall kicks and hard drop lock valid pieces", () => {
  const s = E.context({ random: () => 0.3 });
  for (let i = 0; i < 30; i++) E.move(s, -1, 0);
  assert.equal(E.move(s, -1, 0), false);
  E.rotate(s);
  assert.equal(E.fits(s, s.piece.cells, s.piece.x, s.piece.y), true);
  E.hardDrop(s);
  assert.equal(s.locks, 1);
  assert.equal(s.board.flat().filter(Boolean).length, 4);
});
test("completed rows bank useful types and answer tasks; noise has no context value", () => {
  const s = E.context({ random: () => 0.3 });
  s.board[16] = [
    "instruction",
    "instruction",
    "instruction",
    "instruction",
    "document",
    "document",
    "document",
    "document",
    "noise",
    "noise",
  ];
  s.board[17] = [
    "memory",
    "memory",
    "memory",
    "memory",
    "noise",
    "noise",
    "noise",
    "noise",
    "noise",
    "noise",
  ];
  assert.equal(E.clearRows(s), 2);
  assert.equal(s.tasks, 1);
  assert.equal(s.erasers, 4);
  assert.equal(s.score, 1080);
  assert.equal(s.board.length, 18);
  assert.deepEqual(s.collected, {
    instruction: 0,
    document: 0,
    memory: 0,
    tool: 0,
    mcp: 0,
    skill: 0,
  });
});
test("discard is limited, perks add one charge, and overflow ends a game", () => {
  const s = E.context({ filter: true });
  assert.equal(s.erasers, 4);
  for (let i = 0; i < 4; i++) assert.equal(E.discard(s), true);
  assert.equal(E.discard(s), false);
  s.board[0].fill("noise");
  s.erasers = 1;
  E.discard(s);
  assert.equal(s.status, "lost");
  const before = JSON.stringify(s);
  E.hardDrop(s);
  E.rotate(s);
  E.contextStep(s, 10);
  E.discard(s);
  assert.equal(JSON.stringify(s), before);
});
test("many drops and rotations never create out-of-bounds board writes", () => {
  for (let seed = 1; seed <= 25; seed++) {
    let n = seed;
    const random = () => (n = (n * 1664525 + 1013904223) >>> 0) / 4294967296;
    const s = E.context({ random });
    while (s.status === "playing") {
      for (let j = 0; j < Math.floor(random() * 4); j++) E.rotate(s);
      const dx = random() < 0.5 ? -1 : 1;
      for (let j = 0; j < Math.floor(random() * 10); j++) E.move(s, dx, 0);
      E.hardDrop(s);
      assert.equal(s.board.length, 18);
      assert.ok(s.board.every((row) => row.length === 10));
    }
  }
});
test("existing harness saves migrate and new scores survive reload and reset", () => {
  let saved = JSON.stringify({
    v: 1,
    unlocked: ["tool.browser"],
    played: ["runner"],
    stats: { runnerBest: 91 },
  });
  const context = vm.createContext({
    window: {
      localStorage: {
        getItem: () => saved,
        setItem: (_, v) => {
          saved = v;
        },
      },
    },
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, "arcade.js"), "utf8"),
    context,
  );
  const h = context.window.Amigo.harness;
  assert.equal(h.stats().agentsBest, 0);
  assert.equal(h.stats().runnerBest, 91);
  h.record({ agentsBest: { best: 500 }, contextBest: { best: 1200 } });
  h.unlock("skill.coordination");
  h.invalidate();
  assert.equal(h.stats().agentsBest, 500);
  assert.equal(h.stats().contextBest, 1200);
  assert.equal(h.has("tool.browser"), true);
  assert.equal(h.has("skill.coordination"), true);
  h.played("agents");
  h.played("context");
  assert.equal(h.has("context.brand"), true);
  h.reset();
  assert.equal(h.stats().agentsBest, 0);
  assert.equal(h.has("skill.coordination"), false);
});
test("harness remains playable when storage is blocked", () => {
  const context = vm.createContext({
    window: {
      localStorage: {
        getItem: () => {
          throw Error("blocked");
        },
        setItem: () => {
          throw Error("blocked");
        },
      },
    },
  });
  vm.runInContext(
    fs.readFileSync(path.join(root, "arcade.js"), "utf8"),
    context,
  );
  const h = context.window.Amigo.harness;
  h.record({ contextBest: { best: 99 } });
  h.unlock("data.signal_filter");
  assert.equal(h.stats().contextBest, 99);
  assert.equal(h.has("data.signal_filter"), true);
});

test("tools and MCP cost budget only once and modify work and focus", () => {
  const s = E.office();
  const before = E.officeRate(s);
  assert.equal(E.equip(s, "tool"), true);
  assert.equal(s.budget, 282);
  assert.ok(E.officeRate(s) > before);
  assert.equal(E.equip(s, "tool"), false);
  assert.equal(E.equip(s, "mcp"), true);
  E.focus(s);
  assert.equal(s.cooldown, 9);
  assert.equal(E.equip(s, "unknown"), false);
  s.status = "lost";
  assert.equal(E.equip(s, "docs"), false);
});
test("provider modifiers change actual costs and falling cadence", () => {
  const a = E.office({ provider: "openai" }),
    b = E.office({ provider: "qwen" });
  E.officeStep(a, 1);
  E.officeStep(b, 1);
  assert.ok(a.spent > b.spent);
  assert.ok(a.progress > b.progress);
  const slow = E.context({ provider: "anthropic" }),
    fast = E.context({ provider: "deepseek" });
  E.contextStep(slow, 0.9);
  E.contextStep(fast, 0.9);
  assert.equal(slow.piece.y, 0);
  assert.equal(fast.piece.y, 1);
  assert.equal(E.context({ provider: "qwen" }).erasers, 4);
});
test("cleared AI blocks activate distinct bonuses and retain collectible IDs", () => {
  const s = E.context();
  s.erasers = 1;
  s.board[17] = [
    "tool",
    "tool",
    "tool",
    "tool",
    "mcp",
    "mcp",
    "mcp",
    "mcp",
    "noise",
    "noise",
  ];
  E.clearRows(s);
  assert.equal(s.erasers, 2);
  assert.ok(s.activated.includes("tool"));
  assert.ok(s.activated.includes("mcp"));
  assert.ok(s.score >= 250);
  s.board[17] = [
    "skill",
    "skill",
    "skill",
    "skill",
    "noise",
    "noise",
    "noise",
    "noise",
    "noise",
    "noise",
  ];
  E.clearRows(s);
  assert.equal(s.slow, 15);
  assert.ok(s.activated.includes("skill"));
  E.contextStep(s, 1);
  assert.equal(s.slow, 14);
});
test("equipment unlocked in the shared harness is present on a later office run", () => {
  const s = E.office({
    gear: { tool: true, mcp: true, docs: true, skill: true },
  });
  assert.equal(s.gear.docs, true);
  assert.equal(E.equip(s, "docs"), false);
  assert.equal(s.budget, 300);
});
