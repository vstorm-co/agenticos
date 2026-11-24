import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { findMessageAnchor, revealMessageAnchor, useMessageJump } from "./use-message-jump";

const roots: HTMLElement[] = [];
beforeEach(() => {
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);
});
afterEach(() => {
  roots.splice(0).forEach((root) => root.remove());
  vi.restoreAllMocks();
});
function transcript(id?: string) {
  const root = document.createElement("div");
  document.body.append(root);
  roots.push(root);
  const target = document.createElement("div");
  if (id) target.dataset.messageId = id;
  target.scrollIntoView = vi.fn();
  target.animate = vi.fn();
  root.append(target);
  return { container: { current: root as HTMLElement | null }, target };
}
function options() {
  const { container, target } = transcript("target");
  return {
    target,
    props: {
      messageId: "target" as string | null,
      scope: "account:org:conversation:1",
      revision: 0,
      ready: true,
      messageIds: ["recent"] as string[],
      firstMessageId: "recent" as string | null,
      hasEarlier: true,
      loadingEarlier: false,
      loadEarlier: vi.fn<() => Promise<unknown>>().mockResolvedValue(undefined),
      container,
      beforeJump: vi.fn(),
    },
  };
}

it("finds only anchors inside its transcript, including saved segments and thread roots", () => {
  const { container, target } = transcript("recent");
  target.dataset.messageIds = 'first odd"]id';
  expect(findMessageAnchor(container.current!, "first")).toBe(target);
  expect(findMessageAnchor(container.current!, 'odd"]id')).toBe(target);
  expect(findMessageAnchor(container.current!, "missing")).toBeUndefined();
  const outside = transcript("outside");
  expect(findMessageAnchor(container.current!, "outside")).toBeUndefined();
  outside.target.dataset.threadRoot = "root";
  expect(findMessageAnchor(outside.container.current!, "root")).toBe(outside.target);
});

it("focuses and highlights a loaded match once, and repeats an explicit same-message request", () => {
  const { props, target } = options();
  props.messageIds = ["target"];
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  expect(view.result.current.status).toBe("found");
  expect(target).toHaveFocus();
  expect(target.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  expect(target.animate).toHaveBeenCalledOnce();
  expect(props.loadEarlier).not.toHaveBeenCalled();
  view.rerender({ ...props });
  expect(target.scrollIntoView).toHaveBeenCalledOnce();
  view.rerender({ ...props, revision: 1 });
  expect(target.scrollIntoView).toHaveBeenCalledTimes(2);
});

it("reveals folded work when following a link without closing work already open", () => {
  const { target } = transcript("saved");
  const closed = document.createElement("button");
  closed.dataset.messageDisclosure = "";
  closed.setAttribute("aria-expanded", "false");
  const expand = vi.fn(() => closed.setAttribute("aria-expanded", "true"));
  closed.addEventListener("click", expand);
  const open = document.createElement("button");
  open.dataset.messageDisclosure = "";
  open.setAttribute("aria-expanded", "true");
  const collapse = vi.fn();
  open.addEventListener("click", collapse);
  target.append(closed, open);
  revealMessageAnchor(target);
  revealMessageAnchor(target);
  expect(expand).toHaveBeenCalledOnce();
  expect(collapse).not.toHaveBeenCalled();
  expect(target).toHaveFocus();
});

it("respects reduced motion and can reveal a target after its container mounts", () => {
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList);
  const { props, target } = options();
  props.messageIds = ["target"];
  const root = props.container.current;
  props.container.current = null;
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  expect(target.scrollIntoView).not.toHaveBeenCalled();
  props.container.current = root;
  view.rerender({ ...props });
  expect(target.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "center" });
  expect(target.animate).not.toHaveBeenCalled();
});

it("waits for a known message's anchor to mount without falling back to another transcript", () => {
  const { props, target } = options();
  props.messageIds = ["target"];
  target.dataset.messageId = "different";
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  expect(target.scrollIntoView).not.toHaveBeenCalled();
  expect(props.loadEarlier).not.toHaveBeenCalled();
  target.dataset.messageId = "target";
  view.rerender({ ...props });
  expect(target).toHaveFocus();
});

it("does not duplicate a pending cursor request when loading state toggles before completion", async () => {
  const { props } = options();
  let finish!: () => void;
  props.loadEarlier.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  view.rerender({ ...props, loadingEarlier: true });
  view.rerender({ ...props, loadingEarlier: false });
  expect(props.loadEarlier).toHaveBeenCalledOnce();
  view.unmount();
  await act(async () => {
    finish();
  });
});

it("waits for an authorized current transcript and for an existing page request", () => {
  const { props } = options();
  const view = renderHook((value) => useMessageJump(value), {
    initialProps: { ...props, ready: false },
  });
  expect(view.result.current.status).toBe("loading");
  expect(props.beforeJump).not.toHaveBeenCalled();
  expect(props.loadEarlier).not.toHaveBeenCalled();
  view.rerender({ ...props, ready: true, loadingEarlier: true });
  expect(props.loadEarlier).not.toHaveBeenCalled();
  view.rerender({ ...props, ready: true, messageId: null });
  expect(view.result.current.status).toBe("idle");
});

it("walks backward one page at a time and stops as soon as the matched message is loaded", async () => {
  const { props, target } = options();
  const resolve: Array<() => void> = [];
  props.loadEarlier.mockImplementation(() => new Promise<void>((done) => resolve.push(done)));
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  expect(props.loadEarlier).toHaveBeenCalledOnce();
  view.rerender({ ...props, loadingEarlier: true });
  view.rerender({ ...props, firstMessageId: "middle", messageIds: ["middle", "recent"] });
  expect(props.loadEarlier).toHaveBeenCalledTimes(2);
  await act(async () => {
    resolve[0]!();
  });
  expect(view.result.current.status).toBe("loading");
  view.rerender({ ...props, firstMessageId: "target", messageIds: ["target", "middle", "recent"] });
  await act(async () => {
    resolve[1]!();
  });
  expect(view.result.current.status).toBe("found");
  expect(target).toHaveFocus();
  expect(props.loadEarlier).toHaveBeenCalledTimes(2);
});

it("stops on a swallowed fetch failure or no-progress cursor and retries only on request", async () => {
  const { props } = options();
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  await waitFor(() => expect(view.result.current.status).toBe("failed"));
  expect(props.loadEarlier).toHaveBeenCalledOnce();
  act(() => view.result.current.retry());
  await waitFor(() => expect(props.loadEarlier).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(view.result.current.status).toBe("failed"));
  expect(props.beforeJump).toHaveBeenCalledTimes(2);
});

it("distinguishes exhausted history from a rejected page read", async () => {
  const { props } = options();
  const view = renderHook((value) => useMessageJump(value), {
    initialProps: { ...props, hasEarlier: false },
  });
  expect(view.result.current.status).toBe("unavailable");
  expect(props.loadEarlier).not.toHaveBeenCalled();
  props.loadEarlier.mockRejectedValue(new Error("Access changed"));
  view.rerender(props);
  await waitFor(() => expect(view.result.current.status).toBe("failed"));
  expect(props.loadEarlier).toHaveBeenCalledOnce();
});

it("cancels navigation without starting another read after the in-flight page settles", async () => {
  const { props } = options();
  let finish!: () => void;
  props.loadEarlier.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  act(() => view.result.current.cancel());
  expect(view.result.current.status).toBe("idle");
  view.rerender({ ...props, firstMessageId: "middle", messageIds: ["middle", "recent"] });
  await act(async () => {
    finish();
  });
  expect(view.result.current.status).toBe("idle");
  expect(props.loadEarlier).toHaveBeenCalledOnce();
});

it("ignores a late result from an old account, organization or conversation selection", async () => {
  const { props } = options();
  let reject!: (error: Error) => void;
  props.loadEarlier.mockImplementation(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
  );
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  view.rerender({ ...props, scope: "new-account:new-org:conversation:2", messageIds: ["target"] });
  await act(async () => {
    reject(new Error("Old request"));
  });
  expect(view.result.current.status).toBe("found");
  expect(props.loadEarlier).toHaveBeenCalledOnce();
});

it("ignores a settled request after unmount and tolerates browsers without animation", async () => {
  const { props, target } = options();
  let finish!: () => void;
  props.loadEarlier.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = renderHook((value) => useMessageJump(value), { initialProps: props });
  view.unmount();
  await act(async () => {
    finish();
  });
  Object.defineProperty(target, "animate", { value: undefined });
  expect(() => revealMessageAnchor(target)).not.toThrow();
});
