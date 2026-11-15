import { describe, expect, it } from "vitest";
import { createBrowserPanelStore } from "./browser-panel-store";

describe("a chat's manual workspace selection", () => {
  it("starts closed, opens an idle surface, selects a real visit, and closes both", () => {
    const store = createBrowserPanelStore();
    expect(store.getState()).toMatchObject({ surface: null, openCallId: null });
    store.getState().openSurface("computer");
    expect(store.getState()).toMatchObject({ surface: "computer", openCallId: null });
    store.getState().open("actual-computer-call", "computer");
    expect(store.getState()).toMatchObject({
      surface: "computer",
      openCallId: "actual-computer-call",
    });
    store.getState().open("actual-browser-call");
    expect(store.getState()).toMatchObject({
      surface: "browser",
      openCallId: "actual-browser-call",
    });
    store.getState().openSurface("files");
    expect(store.getState()).toMatchObject({ surface: "files", openCallId: null });
    store.getState().close();
    expect(store.getState()).toMatchObject({ surface: null, openCallId: null });
  });
  it("does not share selections with another conversation scope", () => {
    const first = createBrowserPanelStore();
    const second = createBrowserPanelStore();
    first.getState().openSurface("browser");
    second.getState().openSurface("computer");
    first.getState().close();
    expect(second.getState().surface).toBe("computer");
  });
});
