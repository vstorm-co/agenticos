import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { consoleLink, pointAt } from "./assistant-highlight";

const ORIGIN = "https://console.example";

describe("consoleLink", () => {
  it("reads a console page and the control to point at", () => {
    expect(consoleLink("/agents?highlight=agents-new", ORIGIN)).toEqual({
      path: "/agents",
      anchor: "agents-new",
    });
    expect(consoleLink("/runs?tab=spend#top", ORIGIN)).toEqual({
      path: "/runs?tab=spend#top",
      anchor: null,
    });
  });

  it("keeps a locale prefix, the rest of the query and the hash", () => {
    expect(consoleLink("/pl/agents?highlight=agents-new", ORIGIN)).toEqual({
      path: "/pl/agents",
      anchor: "agents-new",
    });
    expect(consoleLink("/en/runs?tab=spend&highlight=runs-filter#top", ORIGIN)).toEqual({
      path: "/en/runs?tab=spend#top",
      anchor: "runs-filter",
    });
  });

  it("leaves every other link an ordinary link", () => {
    for (const href of [
      null,
      "https://evil.example/agents",
      "//evil.example",
      "#cite-1",
      "agents",
      "/api/v1/agents",
      "/a/../api/v1/agents",
    ]) {
      expect(consoleLink(href, ORIGIN)).toBeNull();
    }
  });

  // #2544: each of these passes a check on the raw string and leaves the
  // console once the URL parser has normalised it.
  it.each([
    "/a/..//evil.example/x",
    "/.//evil.example/x",
    "/%2e%2e//evil.example",
    "/.\\/evil.example",
    "/\\evil.example",
    "/\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
  ])("refuses %j, which normalises off the console", (href) => {
    expect(consoleLink(href, ORIGIN)).toBeNull();
  });

  it("refuses an href the URL parser rejects rather than throwing", () => {
    expect(consoleLink("/\\[", ORIGIN)).toBeNull();
  });
});

describe("pointAt", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("rings a control that is on the page, then lets it go", async () => {
    document.body.innerHTML = `<button data-tour="agents-new">New</button>`;
    const button = document.querySelector("button")!;

    await expect(pointAt("agents-new")).resolves.toBe(true);
    expect(button).toHaveClass("assistant-highlight");

    vi.advanceTimersByTime(3000);
    expect(button).not.toHaveClass("assistant-highlight");
  });

  it("opens the tab a control lives behind, as the walkthrough does", async () => {
    // `agent-instructions` is on the Builder's Build tab in the tour registry.
    document.body.innerHTML = `<button data-tour="agent-tab-build">Build</button>`;
    const tab = document.querySelector("button")!;
    tab.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", `<div data-tour="agent-instructions"></div>`);
    });

    const pointing = pointAt("agent-instructions");
    await vi.advanceTimersByTimeAsync(200);

    await expect(pointing).resolves.toBe(true);
  });

  it("gives up on a control the page never draws", async () => {
    const pointing = pointAt("agent-instructions");
    await vi.advanceTimersByTimeAsync(5000);

    await expect(pointing).resolves.toBe(false);
  });
});
