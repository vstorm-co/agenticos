import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  activateTab,
  isTypingTarget,
  onlyHiddenMatches,
  pulse,
  spotlightPath,
  waitForElement,
} from "./spotlight";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";

describe("activateTab", () => {
  it("switches a Radix tab that a bare click leaves unmoved", () => {
    render(
      <Tabs defaultValue="build">
        <TabsList>
          <TabsTrigger value="build">Build</TabsTrigger>
          <TabsTrigger value="toolbox">Toolbox</TabsTrigger>
        </TabsList>
        <TabsContent value="build">build-panel</TabsContent>
        <TabsContent value="toolbox">toolbox-panel</TabsContent>
      </Tabs>,
    );

    const toolbox = screen.getByRole("tab", { name: "Toolbox" });

    // The bug the tour hit: a bare click does not activate a Radix tab, so the
    // panel — and any spotlight target inside it — never mounts.
    act(() => toolbox.click());
    expect(screen.queryByText("toolbox-panel")).toBeNull();

    // activateTab fires what Radix actually listens to, so the panel mounts.
    act(() => activateTab(toolbox));
    expect(screen.getByText("toolbox-panel")).toBeInTheDocument();
  });
});

describe("spotlightPath", () => {
  it("cuts a hole into a full-viewport rectangle", () => {
    const d = spotlightPath(1000, 800, 100, 100, 200, 50, 12);
    // The outer subpath is the whole viewport...
    expect(d.startsWith("M1000,0 L0,0 L0,800 L1000,800 L1000,0 Z")).toBe(true);
    // ...and the inner subpath opens at the hole's top-left plus the corner radius.
    expect(d).toContain("M112,100");
    expect(d.endsWith("z")).toBe(true);
  });

  it("clamps the corner radius so a control smaller than it never inverts the arcs", () => {
    // r wants 12 but the hole is 10×10, so it is clamped to half the shorter side.
    const d = spotlightPath(1000, 800, 0, 0, 10, 10, 12);
    expect(d).toContain("M5,0");
    // across = 10 - 2*5 = 0: the straight runs collapse, the arcs meet.
    expect(d).toContain("h0");
  });
});

describe("pulse", () => {
  it("plays the click flourish for the hold, then clears it", async () => {
    const element = document.createElement("button");
    const controller = new AbortController();

    const done = pulse(element, controller.signal, 5);
    // The class is on for the whole hold so the CSS animation runs...
    expect(element.classList.contains("tour-click-pulse")).toBe(true);

    await done;
    // ...and off afterwards, so re-highlighting the same element replays it.
    expect(element.classList.contains("tour-click-pulse")).toBe(false);
  });

  it("clears the flourish at once when the wait is aborted", async () => {
    const element = document.createElement("button");
    const controller = new AbortController();
    controller.abort();

    // A reader who moves on mid-pulse must not leave the class stuck on.
    await pulse(element, controller.signal, 10_000);
    expect(element.classList.contains("tour-click-pulse")).toBe(false);
  });
});

describe("waitForElement", () => {
  it("with no timeout, waits for a target that mounts late rather than giving up", async () => {
    const controller = new AbortController();
    const pending = waitForElement('[data-tour="late"]', controller.signal, null);

    const el = document.createElement("div");
    el.setAttribute("data-tour", "late");
    document.body.appendChild(el);

    expect(await pending).toBe(el);
    el.remove();
  });

  it("with no timeout, still ends when the wait is aborted", async () => {
    const controller = new AbortController();
    const pending = waitForElement('[data-tour="never"]', controller.signal, null);
    controller.abort();

    expect(await pending).toBeNull();
  });

  it("skips a hidden copy of the control and takes the one on screen", async () => {
    // The navigation exists twice: a desktop column that is `display: none` below
    // `md`, and a drawer. Handed the hidden copy, the coach measured a zero-sized
    // box — a full-viewport freeze with a 0x0 cut-out, over a page whose hamburger
    // was now unreachable, waiting for a click nobody could make.
    const hiddenHost = document.createElement("div");
    hiddenHost.style.display = "none";
    const hidden = document.createElement("a");
    hidden.setAttribute("data-tour", "nav-agents");
    hiddenHost.appendChild(hidden);
    document.body.appendChild(hiddenHost);

    const shown = document.createElement("a");
    shown.setAttribute("data-tour", "nav-agents");
    document.body.appendChild(shown);

    const controller = new AbortController();
    expect(await waitForElement('[data-tour="nav-agents"]', controller.signal, null)).toBe(shown);

    hiddenHost.remove();
    shown.remove();
  });

  it("keeps waiting while every copy is hidden, then takes the one that is revealed", async () => {
    const host = document.createElement("div");
    host.style.display = "none";
    const link = document.createElement("a");
    link.setAttribute("data-tour", "nav-agents");
    host.appendChild(link);
    document.body.appendChild(host);

    const controller = new AbortController();
    const pending = waitForElement('[data-tour="nav-agents"]', controller.signal, null);

    // The drawer opening is a style change on an element already in the document,
    // which a childList-only watch would never see.
    host.style.display = "block";

    expect(await pending).toBe(link);
    host.remove();
  });

  it("reads where a key landed, so the arrows never eat a keystroke", () => {
    // Arrow keys step the walkthrough, but the coach guides readers into create
    // dialogs where the same keys move a caret — and a Radix select navigates its
    // own options with them.
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const editor = document.createElement("div");
    // The attribute, which is what `contentEditable = "true"` reflects to in a
    // browser and what jsdom (which does not implement the property) can carry.
    editor.setAttribute("contenteditable", "true");
    const combo = document.createElement("div");
    combo.setAttribute("role", "combobox");
    const inCombo = document.createElement("span");
    combo.appendChild(inCombo);
    const plain = document.createElement("button");
    for (const node of [input, textarea, editor, combo, plain]) document.body.appendChild(node);

    expect(isTypingTarget(input)).toBe(true);
    expect(isTypingTarget(textarea)).toBe(true);
    expect(isTypingTarget(editor)).toBe(true);
    expect(isTypingTarget(inCombo)).toBe(true);
    expect(isTypingTarget(plain)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);

    for (const node of [input, textarea, editor, combo, plain]) node.remove();
  });

  it("reports a control that exists but is rendered nowhere", () => {
    expect(onlyHiddenMatches('[data-tour="absent"]')).toBe(false);

    const host = document.createElement("div");
    host.style.visibility = "hidden";
    const link = document.createElement("a");
    link.setAttribute("data-tour", "tucked-away");
    host.appendChild(link);
    document.body.appendChild(host);
    expect(onlyHiddenMatches('[data-tour="tucked-away"]')).toBe(true);

    host.style.visibility = "visible";
    expect(onlyHiddenMatches('[data-tour="tucked-away"]')).toBe(false);
    host.remove();
  });
});
