#!/usr/bin/env node
/**
 * Deterministic browser/API fixture against the real Next chat page.
 * This is deliberately separate from backend-seeded frontend/e2e.
 */
import { chromium, expect } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { createConnection } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { installFixture, THREAD, QUESTION, ANSWER } from "./fixtures.mjs";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const args = process.argv.slice(2);
function option(name, fallback) {
  const index = args.indexOf("--" + name);
  return index < 0 ? fallback : args[index + 1];
}
const stage = option("stage", "baseline");
if (!/^[a-z0-9][a-z0-9-]*$/i.test(stage)) throw new Error("Use a simple stage name.");
const baseURL = option("base-url", "http://127.0.0.1:3217");
if (!["127.0.0.1", "localhost", "[::1]"].includes(new URL(baseURL).hostname))
  throw new Error("UI fixture accepts a loopback app origin only.");
const output = path.resolve(frontend, option("output", ".qa/ui-craft/" + stage));
const channel = option("channel", process.env.UI_CRAFT_BROWSER_CHANNEL);
const only = option("viewport", "");
const captureOnly = args.includes("--capture-only");
const extraStates = args.includes("--extra-states");
const packageJSON = JSON.parse(await readFile(path.join(frontend, "package.json"), "utf8"));
const viewports = [
  { width: 1440, height: 1000 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
  { width: 320, height: 740 },
].filter((v) => !only || only === String(v.width));
if (!viewports.length) throw new Error("No matching viewport.");
await mkdir(output, { recursive: true });
let revision = "unknown";
try { revision = execFileSync("git", ["rev-parse", "HEAD"], { cwd: frontend, encoding: "utf8" }).trim(); }
catch { /* Snapshot still records file content hashes. */ }
const sourceFiles = [
  "src/components/chat/chat-container.tsx", "src/components/chat/chat-input.tsx",
  "src/components/chat/composer-editor.tsx", "src/components/chat/message-item.tsx",
  "src/components/chat/markdown-content.impl.tsx", "src/components/chat/markdown-table.tsx",
  "src/components/chat/chat-controls.tsx", "src/components/chat/composer-sheet.tsx",
  "src/components/chat/agent-picker.tsx", "src/components/chat/conversation-sidebar.tsx",
  "src/components/layout/app-sidebar.tsx", "src/components/layout/main-viewport.tsx",
  "src/app/globals.css",
];
const sourceHashes = {};
for (const file of sourceFiles) {
  try { sourceHashes[file] = createHash("sha256").update(await readFile(path.join(frontend, file))).digest("hex"); }
  catch { sourceHashes[file] = "not-present"; }
}
const report = {
  scope: "Real Next chat UI with deterministic browser API fixtures and a mocked chat WebSocket. Not backend E2E.",
  mode: captureOnly ? "geometry-and-captures" : "geometry-captures-and-interactions",
  extraStates,
  stage, baseURL, revision, sourceHashes, capturedAt: new Date().toISOString(),
  assumptions: ["Next server is started with BACKEND_URL=http://127.0.0.1:9.",
    "Browser routing does not intercept server-side requests.",
    "All conversation content, identities, files, and model replies are synthetic.",
    "IME check uses composition DOM events; it does not replace testing a native IME or phone keyboard."],
  viewports: [],
};
async function waitForLoopbackServer() {
  const address = new URL(baseURL);
  const deadline = Date.now() + 240000;
  console.log("Waiting for the local Next server at " + address.host);
  while (Date.now() < deadline) {
    const ready = await new Promise((resolve) => {
      const socket = createConnection({
        host: address.hostname.replace(/^\[|\]$/g, ""),
        port: Number(address.port || (address.protocol === "https:" ? 443 : 80)),
      });
      const finish = (connected) => { socket.destroy(); resolve(connected); };
      socket.setTimeout(1000);
      socket.once("connect", () => finish(true));
      socket.once("error", () => finish(false));
      socket.once("timeout", () => finish(false));
    });
    if (ready) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Local Next server did not listen within 240s: " + address.host);
}
await waitForLoopbackServer().catch(async (error) => {
  report.bootstrapError = error.message;
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
  throw error;
});
const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });

function unique(values) {
  return [...new Map(values.map((value) => [JSON.stringify(value), value])).values()];
}
async function settle(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}
async function geometry(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" &&
        Number(style.opacity) !== 0 && box.width > 0 && box.height > 0;
    };
    const describe = (element) => ({
      tag: element.tagName.toLowerCase(),
      name: element.getAttribute("aria-label") || element.getAttribute("title") ||
        element.textContent?.trim().slice(0, 90) || "",
      x: Math.round(element.getBoundingClientRect().x * 100) / 100,
      right: Math.round(element.getBoundingClientRect().right * 100) / 100,
      width: Math.round(element.getBoundingClientRect().width * 100) / 100,
    });
    const composer = document.querySelector('[data-tour="chat-composer"]');
    const composerBox = composer?.getBoundingClientRect();
    const controls = composer
      ? [...composer.querySelectorAll("button, [contenteditable=true], [role=combobox]")]
          .filter(visible)
      : [];
    const outsideComposer = composerBox ? controls.filter((element) => {
      const box = element.getBoundingClientRect();
      return box.left < composerBox.left - 1 || box.right > composerBox.right + 1 ||
        box.bottom > composerBox.bottom + 1;
    }).map(describe) : [{ error: "composer missing" }];
    const outsideViewport = controls.filter((element) => {
      const box = element.getBoundingClientRect();
      return box.left < -1 || box.right > innerWidth + 1 ||
        box.bottom > innerHeight + 1 || box.top < -1;
    }).map(describe);
    const scroller = document.querySelector("[data-chat-scroller]");
    const transcript = document.querySelector("[data-transcript]");
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
      },
      composer: composerBox ? {
        x: composerBox.x, y: composerBox.y, width: composerBox.width,
        height: composerBox.height, bottom: composerBox.bottom,
      } : null,
      outsideComposer, outsideViewport,
      scroller: scroller ? {
        clientWidth: scroller.clientWidth, scrollWidth: scroller.scrollWidth,
        clientHeight: scroller.clientHeight, scrollHeight: scroller.scrollHeight,
        scrollTop: scroller.scrollTop,
      } : null,
      transcript: transcript ? {
        clientWidth: transcript.clientWidth, scrollWidth: transcript.scrollWidth,
      } : null,
    };
  });
}
async function check(result, name, run) {
  try {
    const evidence = await run();
    result.checks.push({ name, status: "pass", ...(evidence === undefined ? {} : { evidence }) });
  } catch (error) {
    result.checks.push({ name, status: "fail", error: String(error.message || error).slice(0, 2000) });
  }
}
async function withinViewport(locator) {
  const boxes = await locator.evaluateAll((elements) => elements
    .filter((e) => {
      const style = getComputedStyle(e);
      const box = e.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && box.width > 0;
    })
    .map((e) => {
      const b = e.getBoundingClientRect();
      return { left: b.left, right: b.right, top: b.top, bottom: b.bottom,
        width: innerWidth, height: innerHeight };
    }));
  expect(boxes.length, "an open surface must exist").toBeGreaterThan(0);
  for (const b of boxes) {
    expect(b.left).toBeGreaterThanOrEqual(-1);
    expect(b.right).toBeLessThanOrEqual(b.width + 1);
    expect(b.top).toBeGreaterThanOrEqual(-1);
    expect(b.bottom).toBeLessThanOrEqual(b.height + 1);
  }
  return boxes;
}
async function runInteractions(page, fixture, result) {
  const editor = page.locator('[data-tour="chat-composer"] [contenteditable="true"]');
  await check(result, "typing and Shift+Enter preserve the draft without sending", async () => {
    await editor.fill("First handover note");
    await editor.press("End");
    await editor.press("Shift+Enter");
    await editor.pressSequentially("Second line");
    expect(await editor.innerText()).toContain("First handover note");
    expect(await editor.innerText()).toContain("Second line");
    expect((await editor.innerText()).includes("\n")).toBe(true);
    expect(fixture.record.submitted).toHaveLength(0);
  });
  await check(result, "expanded multiline composer remains contained", async () => {
    await settle(page);
    const expanded = await geometry(page);
    expect(expanded.outsideComposer).toEqual([]);
    expect(expanded.outsideViewport).toEqual([]);
    return expanded.composer;
  });
  await check(result, "composition Enter preserves the draft without sending", async () => {
    const before = fixture.record.submitted.length;
    const draftBefore = await editor.innerText();
    await editor.dispatchEvent("compositionstart", { data: "" });
    await editor.dispatchEvent("keydown", {
      key: "Enter", code: "Enter", keyCode: 229, which: 229, isComposing: true, bubbles: true,
    });
    await editor.dispatchEvent("compositionend", { data: "" });
    await settle(page);
    expect(fixture.record.submitted).toHaveLength(before);
    expect(await editor.innerText()).toBe(draftBefore);
  });
  await check(result, "send posts once through the mocked WebSocket", async () => {
    await editor.fill("Please confirm the next checkpoint.");
    const before = fixture.record.submitted.length;
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect.poll(() => fixture.record.submitted.length).toBe(before + 1);
    expect(fixture.record.submitted.at(-1)).toBe("Please confirm the next checkpoint.");
    const answer = page.locator('[data-message-id="fixture-sent-assistant-' + (before + 1) + '"]');
    await expect(answer).toContainText(
      "The handover now has a clear owner",
    );
    await expect(editor).toHaveText("");
  });
  await check(result, "message actions are discoverable and operable with keyboard", async () => {
    const message = page.locator('[data-message-id="fixture-assistant-2"]');
    await message.scrollIntoViewIfNeeded();
    const more = message.getByRole("button", { name: "More", exact: true });
    if (await more.isVisible()) {
      await more.focus();
      await more.press("Enter");
    }
    const reply = message.getByRole("button", { name: "Reply", exact: true });
    const copy = message.getByRole("button", { name: "Copy to clipboard", exact: true });
    await copy.focus();
    await copy.press("Tab");
    await expect(reply).toBeFocused();
    const opacity = await reply.evaluate((element) => Number(getComputedStyle(element).opacity));
    expect(opacity, "focused action must be visible").toBeGreaterThan(0);
    await reply.press("Enter");
    await expect(editor).toBeFocused();
    const cancel = page.getByRole("button", { name: "Don't reply", exact: true });
    if (await cancel.count()) await cancel.first().click();
    return { focusedOpacity: opacity };
  });
  await check(result, "composer menu stays inside the viewport", async () => {
    await page.getByRole("button", { name: "Add to message", exact: true }).click();
    try {
      const surface = page.locator('[role="dialog"]:visible, [role="menu"]:visible');
      await expect(surface.first()).toBeVisible();
      const evidence = await withinViewport(surface);
      await page.screenshot({ path: path.join(output, result.size + "-menu.png"), animations: "disabled" });
      return evidence;
    } finally {
      await page.keyboard.press("Escape");
    }
  });
  await check(result, "agent picker contains the long agent title", async () => {
    await page.locator('[data-tour="chat-agent-picker"]:visible').click();
    try {
      const surface = page.locator('[role="dialog"]:visible');
      await expect(surface.first()).toBeVisible();
      const evidence = await withinViewport(surface);
      await page.screenshot({ path: path.join(output, result.size + "-agent-picker.png"), animations: "disabled" });
      return evidence;
    } finally {
      await page.keyboard.press("Escape");
    }
  });
  await check(result, "model controls remain contained when expanded", async () => {
    let openedSheet = false;
    try {
      if (await page.locator('[data-tour="chat-settings"]:visible').count() === 0) {
        await page.getByRole("button", { name: "Add to message", exact: true }).click();
        openedSheet = true;
      }
      await page.locator('[data-tour="chat-settings"]:visible').first().click();
      await page.getByRole("button", { name: "Change model", exact: true }).click();
      const evidence = await withinViewport(page.locator('[role="dialog"]:visible'));
      await page.screenshot({ path: path.join(output, result.size + "-model-controls.png"), animations: "disabled" });
      return evidence;
    } finally {
      await page.keyboard.press("Escape");
      if (openedSheet) await page.keyboard.press("Escape");
    }
  });
  await check(result, "reading position survives streamed content growth", async () => {
    await page.keyboard.press("Escape");
    fixture.holdNextReply();
    await editor.fill("Add one more checkpoint while I review the earlier notes.");
    await page.getByRole("button", { name: "Send message", exact: true }).click();
    await expect.poll(() => fixture.hasHeldReply()).toBe(true);
    const scroller = page.locator("[data-chat-scroller]");
    const box = await scroller.boundingBox();
    if (!box) throw new Error("Transcript scroller missing.");
    await page.mouse.move(box.x + box.width / 2, box.y + 100);
    await page.mouse.wheel(0, -650);
    await expect.poll(() => scroller.evaluate((e) => e.scrollTop)).toBeLessThan(
      await scroller.evaluate((e) => e.scrollHeight - e.clientHeight - 30),
    );
    await settle(page);
    const before = await scroller.evaluate((e) => e.scrollTop);
    fixture.appendHeldReply("\n\n" + Array(12).fill(
      "The checkpoint remains assigned to the shift owner, with a clear time for follow-up.",
    ).join("\n\n"));
    await expect(scroller).toContainText("The checkpoint remains assigned to the shift owner");
    await settle(page);
    const after = await scroller.evaluate((e) => e.scrollTop);
    fixture.finishHeldReply();
    expect(Math.abs(after - before), "streaming should not move the reader").toBeLessThanOrEqual(3);
    return { before, after };
  });
}

async function captureExtraStates(page, fixture, result) {
  const submittedBefore = fixture.record.submitted.length;
  fixture.finishHeldReply();
  await check(result, "empty chat is usable and contained", async () => {
    await page.goto(baseURL + "/chat", { waitUntil: "domcontentloaded", timeout: 240000 });
    const editor = page.locator('[data-tour="chat-composer"] [contenteditable="true"]');
    await expect(editor).toBeEditable({ timeout: 60000 });
    await expect(page.locator("[data-message-id]")).toHaveCount(0);
    await expect(page.locator('[data-tour="chat-agent-picker"]:visible')).toBeVisible();
    await settle(page);
    const empty = await geometry(page);
    expect(empty.document.scrollWidth).toBeLessThanOrEqual(empty.document.clientWidth + 1);
    expect(empty.outsideComposer).toEqual([]);
    expect(empty.outsideViewport).toEqual([]);
    await page.screenshot({ path: path.join(output, result.size + "-empty.png"), animations: "disabled" });
    return empty;
  });
  await check(result, "focused multiline draft is contained and remains unsent", async () => {
    const editor = page.locator('[data-tour="chat-composer"] [contenteditable="true"]');
    await editor.fill([
      "Review the handover and flag any follow-up without an owner.",
      "",
      "Reference: https://docs.example.test/operations/service-desk/handover/november-2026/customer-follow-up",
      "Please keep the answer easy for the next shift to scan.",
    ].join("\n"));
    await editor.focus();
    await editor.press("End");
    await settle(page);
    const draft = await geometry(page);
    expect(draft.document.scrollWidth).toBeLessThanOrEqual(draft.document.clientWidth + 1);
    expect(draft.outsideComposer).toEqual([]);
    expect(draft.outsideViewport).toEqual([]);
    expect(fixture.record.submitted.length).toBe(submittedBefore);
    await page.screenshot({ path: path.join(output, result.size + "-focused-draft.png"), animations: "disabled" });
    return draft;
  });
}

try {
  for (const viewport of viewports) {
    const size = viewport.width + "x" + viewport.height;
    const result = { size, viewport, checks: [], consoleErrors: [], pageErrors: [] };
    report.viewports.push(result);
    const context = await browser.newContext({
      viewport, deviceScaleFactor: 1, colorScheme: "light", reducedMotion: "reduce",
      locale: "en-GB", timezoneId: "UTC", serviceWorkers: "block",
    });
    const fixture = await installFixture(context, { baseURL, version: packageJSON.version });
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.setDefaultNavigationTimeout(240000);
    page.on("pageerror", (error) => result.pageErrors.push(error.message));
    page.on("console", (entry) => { if (entry.type() === "error") result.consoleErrors.push(entry.text()); });
    try {
      console.log(size + ": opening seeded chat (initial Next compilation may take up to 240s)");
      await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
      await page.clock.setFixedTime(new Date("2026-11-07T09:00:00Z"));
      await page.goto(baseURL + "/chat?id=" + THREAD, { waitUntil: "domcontentloaded", timeout: 240000 });
      console.log(size + ": document loaded; waiting for the seeded transcript");
      await expect(page.locator('[data-message-id="fixture-user-1"]')).toContainText(QUESTION, { timeout: 120000 });
      await expect(page.locator('[data-message-id="fixture-assistant-1"]')).toContainText(ANSWER);
      // Markdown is a lazy Next chunk. The fallback contains the same text but
      // its literal pipes/fences do not exercise the real table or code layout.
      const richAnswer = page.locator('[data-message-id="fixture-assistant-1"]');
      await expect(richAnswer.locator("table")).toBeAttached({ timeout: 120000 });
      await expect(richAnswer.locator("pre").first()).toBeAttached({ timeout: 30000 });
      await expect(page.locator('[data-tour="chat-composer"] [contenteditable="true"]')).toBeEditable();
      console.log(size + ": seeded transcript and writable composer ready");
      await settle(page);
      result.geometry = await geometry(page);
      await check(result, "seeded transcript rendered", async () => {
        expect(await page.locator("[data-message-id]").count()).toBeGreaterThanOrEqual(4);
        expect(await richAnswer.locator("table").count()).toBe(1);
        expect(await richAnswer.locator("pre").count()).toBeGreaterThan(0);
      });
      await check(result, "page has no horizontal overflow", async () => {
        const g = result.geometry;
        expect(g.document.scrollWidth).toBeLessThanOrEqual(g.document.clientWidth + 1);
        expect(g.document.bodyScrollWidth).toBeLessThanOrEqual(g.document.clientWidth + 1);
        expect(g.scroller.scrollWidth).toBeLessThanOrEqual(g.scroller.clientWidth + 1);
      });
      await check(result, "composer and controls remain inside their bounds", async () => {
        expect(result.geometry.outsideComposer).toEqual([]);
        expect(result.geometry.outsideViewport).toEqual([]);
      });
      await page.screenshot({ path: path.join(output, size + ".png"), animations: "disabled" });
      // A second unchanged view proves long Markdown/code/table/filename containment.
      await page.locator("[data-chat-scroller]").evaluate((e) => { e.scrollTop = 0; });
      await settle(page);
      await page.screenshot({ path: path.join(output, size + "-long-content.png"), animations: "disabled" });
      if (!captureOnly) await runInteractions(page, fixture, result);
      if (extraStates && [1440, 390].includes(viewport.width))
        await captureExtraStates(page, fixture, result);
    } catch (error) {
      result.checks.push({ name: "fixture setup and capture", status: "fail", error: String(error.message || error) });
      await page.screenshot({ path: path.join(output, size + "-setup-failure.png"), animations: "disabled", timeout: 5000 }).catch(() => {});
      result.bodyText = await page.locator("body").innerText({ timeout: 3000 })
        .then((text) => text.slice(0, 12000))
        .catch((readError) => "Body unavailable: " + String(readError.message || readError).slice(0, 500));
    } finally {
      result.network = {
        ...fixture.record,
        mockedRequests: unique(fixture.record.mockedRequests),
        unexpectedRequests: unique(fixture.record.unexpectedRequests),
        blockedExternal: unique(fixture.record.blockedExternal),
      };
      await check(result, "all API requests handled by explicit fixture routes", async () => {
        expect(result.network.unexpectedRequests).toEqual([]);
      });
      await check(result, "no runtime page errors", async () => {
        expect(result.pageErrors).toEqual([]);
      });
      await check(result, "no unexpected external browser requests", async () => {
        expect(result.network.blockedExternal).toEqual([]);
      });
      fixture.dispose();
      await context.close();
      await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
      const failures = result.checks.filter((c) => c.status === "fail");
      console.log(size + ": " + (result.checks.length - failures.length) + "/" + result.checks.length + " passed");
      for (const failure of failures) console.log("  FAIL " + failure.name + ": " + failure.error.slice(0, 400));
    }
  }
} finally {
  await browser.close();
}
const failed = report.viewports.flatMap((v) =>
  v.checks.filter((c) => c.status === "fail").map((c) => ({ viewport: v.size, ...c })),
);
const summary = [
  "# UI craft browser fixture — " + stage,
  "",
  report.scope,
  "",
  "This run uses synthetic data and a mocked WebSocket. It does not validate backend authorization, persistence, uploads, real model streaming, or native mobile keyboards.",
  "",
  "| Viewport | Passed | Failed |",
  "| --- | ---: | ---: |",
  ...report.viewports.map((v) => "| " + v.size + " | " +
    v.checks.filter((c) => c.status === "pass").length + " | " +
    v.checks.filter((c) => c.status === "fail").length + " |"),
  "",
  "See report.json for checks, measurements, source hashes, and intercepted requests.",
  "",
  ...(failed.length ? ["## Failures", "", ...failed.map((f) =>
    "- " + f.viewport + " — " + f.name + ": " + f.error.replace(/\s+/g, " ").slice(0, 500))] : []),
  "",
].join("\n");
await writeFile(path.join(output, "README.md"), summary);
console.log("Evidence: " + output);
process.exitCode = failed.length ? 1 : 0;
