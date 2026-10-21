import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity } from "@/lib/desktop/blobby-engine";

import { Blobby, type Heard } from "./blobby";
import { DESKTOP_STATE } from "./fixtures";

const env = vi.hoisted(() => ({
  motion: {
    state: "idle" as string,
    facing: 1 as 1 | -1,
    gaze: null,
    react: vi.fn(),
    startDragging: vi.fn(),
  },
  options: null as null | { onQuip: () => void; still: boolean },
  commands: {
    openChat: vi.fn(async () => {}),
    openInConsole: vi.fn(async () => {}),
    showBlobbyMenu: vi.fn(async () => {}),
    showConsole: vi.fn(async () => {}),
  },
  report: vi.fn(),
  face: vi.fn(),
}));
vi.mock("@/hooks/use-blobby-motion", () => ({
  useBlobbyMotion: (options: { onQuip: () => void; still: boolean }) => {
    env.options = options;
    return env.motion;
  },
}));
vi.mock("@/lib/desktop/commands", () => env.commands);
vi.mock("@/lib/desktop/shell", () => ({ reportShellFailure: env.report }));
vi.mock("@/components/desktop/blobby-face", () => ({
  BlobbyFace: (props: { expression: string }) => {
    env.face(props);
    return <span data-testid="face">{props.expression}</span>;
  },
}));

const quiet: Activity = { kind: "quiet" };

function show(
  props: Partial<{
    activity: Activity;
    signedIn: boolean;
    heard: Heard | null;
    activityOn: boolean;
  }> = {},
) {
  return render(
    <Blobby
      settings={{ ...DESKTOP_STATE.blobby, activity: props.activityOn ?? true }}
      activity={props.activity ?? quiet}
      signedIn={props.signedIn ?? true}
      heard={props.heard ?? null}
      reducedMotion={false}
    />,
  );
}

const body = () => screen.getByRole("button", { name: /^Blobby\./ });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  env.motion.state = "idle";
  env.motion.facing = 1;
  vi.clearAllMocks();
});

afterEach(() => vi.useRealTimers());

describe("Blobby", () => {
  it("waves and says one of its lines when clicked, and the line goes after a while", () => {
    show();
    fireEvent.pointerDown(body(), { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerUp(body());
    expect(env.motion.react).toHaveBeenCalledWith("wave", expect.any(Number));
    expect(screen.getByRole("status")).not.toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.queryByRole("button", { name: /New chat/ })).toBeInTheDocument();
  });

  it("hops and brings the console forward on a double click", () => {
    show();
    for (let i = 0; i < 2; i++) {
      fireEvent.pointerDown(body(), { button: 0, clientX: 10, clientY: 10 });
      fireEvent.pointerUp(body());
    }
    expect(env.motion.react).toHaveBeenLastCalledWith("hop", expect.any(Number));
    expect(env.commands.showConsole).toHaveBeenCalled();
  });

  it("is dragged once the press moves, and ignores a right button and a cancelled press", () => {
    show();
    fireEvent.pointerDown(body(), { button: 2 });
    fireEvent.pointerUp(body());
    expect(env.motion.react).not.toHaveBeenCalled();
    fireEvent.pointerDown(body(), { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(body(), { clientX: 11, clientY: 10 });
    expect(env.motion.startDragging).not.toHaveBeenCalled();
    fireEvent.pointerMove(body(), { clientX: 30, clientY: 10 });
    expect(env.motion.startDragging).toHaveBeenCalled();
    fireEvent.pointerDown(body(), { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerCancel(body());
    fireEvent.pointerUp(body());
    expect(env.motion.react).not.toHaveBeenCalled();
  });

  it("is pleased when stroked", () => {
    show();
    let time = 0;
    for (const x of [10, 20, 10, 20, 10, 20]) {
      vi.setSystemTime(time);
      time += 100;
      fireEvent.pointerMove(body(), { clientX: x, clientY: 5 });
    }
    expect(env.motion.react).toHaveBeenCalledWith("happy", expect.any(Number));
  });

  it("opens the shell's menu on a right click, and greets the keyboard", () => {
    show();
    fireEvent.contextMenu(body());
    expect(env.commands.showBlobbyMenu).toHaveBeenCalled();
    fireEvent.keyDown(body(), { key: "Enter" });
    fireEvent.keyDown(body(), { key: "x" });
    expect(env.motion.react).toHaveBeenCalledTimes(1);
  });

  it("opens a new chat from the button over its head", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
    expect(env.commands.openChat).toHaveBeenCalled();
  });

  it("says what the agents are doing, opens it on click, and stops saying it after a while", () => {
    show({ activity: { kind: "approvals", count: 2 } });
    expect(screen.getByTestId("face")).toHaveTextContent("surprised");
    fireEvent.click(screen.getByRole("button", { name: "2 approvals are waiting for you" }));
    expect(env.commands.openInConsole).toHaveBeenCalledWith("/runs?tab=approvals");
    act(() => vi.advanceTimersByTime(7000));
    expect(screen.queryByText("2 approvals are waiting for you")).toBeNull();
  });

  it("words each kind of activity, and keeps quiet about it when asked to", () => {
    const { rerender } = show({ activity: { kind: "unread", count: 1 } });
    expect(screen.getByText("One new notification")).toBeInTheDocument();
    const settings = DESKTOP_STATE.blobby;
    rerender(
      <Blobby
        settings={settings}
        activity={{ kind: "running", count: 3 }}
        signedIn
        heard={null}
        reducedMotion={false}
      />,
    );
    expect(screen.getByText("Your agents are on 3 runs")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Your agents are on 3 runs"));
    expect(env.commands.openInConsole).toHaveBeenCalledWith("/runs");
    rerender(
      <Blobby
        settings={{ ...settings, activity: false }}
        activity={{ kind: "running", count: 4 }}
        signedIn
        heard={null}
        reducedMotion={false}
      />,
    );
    expect(screen.queryByText(/runs/)).toBeNull();
  });

  it("says what the shell asked it to, and nothing opens from that", () => {
    show({ heard: { text: "Allow screen recording, then restart me.", id: 1 } });
    fireEvent.click(screen.getByText("Allow screen recording, then restart me."));
    expect(env.commands.openInConsole).not.toHaveBeenCalled();
  });

  it("dozes, and says where to sign in, with nobody signed in", () => {
    show({ signedIn: false });
    expect(screen.getByTestId("face")).toHaveTextContent("sleepy");
    expect(env.options?.still).toBe(true);
    expect(screen.queryByRole("button", { name: /New chat/ })).toBeNull();
    fireEvent.pointerDown(body(), { button: 0, clientX: 1, clientY: 1 });
    fireEvent.pointerUp(body());
    expect(
      screen.getByText("Sign in in the console and I'll keep you posted."),
    ).toBeInTheDocument();
  });

  it("speaks when its motion says so, and faces the way it strolls", () => {
    env.motion.state = "stroll";
    env.motion.facing = -1;
    show();
    expect(body()).toHaveStyle({ scale: "-1 1" });
    act(() => env.options?.onQuip());
    expect(screen.getByRole("status")).not.toBeEmptyDOMElement();
  });

  it("reports a command the shell refused", async () => {
    env.commands.openChat.mockRejectedValueOnce(new Error("refused"));
    show();
    fireEvent.click(screen.getByRole("button", { name: /New chat/ }));
    await vi.waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not open a new chat", expect.any(Error)),
    );
  });
});
