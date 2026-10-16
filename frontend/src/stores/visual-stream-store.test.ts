import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addVisualImages,
  appendVisualArgs,
  dropVisualArgs,
  rememberSavedVisual,
  resetVisualState,
  useSavedVisualsStore,
  useVisualImagesStore,
  useVisualStreamStore,
} from "./visual-stream-store";

describe("streamed visual arguments", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useVisualStreamStore.setState({ args: {} });
  });
  afterEach(() => vi.useRealTimers());

  it("gathers text deltas and publishes them at most every flush", () => {
    appendVisualArgs("c", '{"title": ');
    appendVisualArgs("c", '"Flow"');
    expect(useVisualStreamStore.getState().args).toEqual({});
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args).toEqual({ c: '{"title": "Flow"' });
    appendVisualArgs("c", "}");
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args.c).toBe('{"title": "Flow"}');
  });

  it("merges object deltas key by key, as Pydantic AI does", () => {
    appendVisualArgs("c", { title: "A" });
    appendVisualArgs("c", { content: "<svg" });
    appendVisualArgs("c", { title: "B" });
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args.c).toEqual({ title: "B", content: "<svg" });
  });

  it("starts over when a provider switches between text and objects", () => {
    appendVisualArgs("c", { title: "A" });
    appendVisualArgs("c", "text");
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args.c).toBe("text");
    appendVisualArgs("c", { title: "B" });
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args.c).toEqual({ title: "B" });
  });

  it("ignores a delta that is neither", () => {
    appendVisualArgs("c", 3);
    appendVisualArgs("c", ["x"]);
    appendVisualArgs("c", null);
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args).toEqual({});
  });

  it("forgets a call, pending text included", () => {
    appendVisualArgs("c", "a");
    vi.advanceTimersByTime(100);
    appendVisualArgs("c", "b");
    dropVisualArgs("c");
    vi.advanceTimersByTime(100);
    expect(useVisualStreamStore.getState().args).toEqual({});
    dropVisualArgs("never");
    expect(useVisualStreamStore.getState().args).toEqual({});
  });
});

describe("pictures and saved apps", () => {
  it("adds pictures to a visual without losing the ones it had", () => {
    useVisualImagesStore.setState({ images: {} });
    addVisualImages("v", { a: "data:a" });
    addVisualImages("v", { b: "data:b" });
    expect(useVisualImagesStore.getState().images).toEqual({ v: { a: "data:a", b: "data:b" } });
  });

  it("remembers the app a visual was saved as", () => {
    useSavedVisualsStore.setState({ saved: {} });
    rememberSavedVisual("v", { artifactId: "a", name: "flow", version: 2, url: "/apps/a" });
    expect(useSavedVisualsStore.getState().saved.v!.version).toBe(2);
  });
});

describe("resetVisualState", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("forgets every call's arguments, pictures and saved app, pending text included", () => {
    appendVisualArgs("call_0", "a");
    vi.advanceTimersByTime(100);
    appendVisualArgs("call_0", "b");
    addVisualImages("call_0", { a: "data:a" });
    rememberSavedVisual("call_0", { artifactId: "a", name: "flow", version: 1, url: "/apps/a" });

    resetVisualState();
    vi.advanceTimersByTime(100);

    expect(useVisualStreamStore.getState().args).toEqual({});
    expect(useVisualImagesStore.getState().images).toEqual({});
    expect(useSavedVisualsStore.getState().saved).toEqual({});
    resetVisualState();
  });
});
