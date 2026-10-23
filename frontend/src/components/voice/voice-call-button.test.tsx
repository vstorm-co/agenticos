import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { VoiceReadiness } from "@/types/voice";

import { VoiceCallButton } from "./voice-call-button";

const READY: VoiceReadiness = {
  available: true,
  unavailable: null,
  transport: "webrtc",
  provider: "openai",
  model: "gpt-realtime",
  cap_seconds: 600,
};

const NAME = "Start a voice call";

describe("VoiceCallButton", () => {
  it("starts a call when the agent is ready", () => {
    const onStart = vi.fn();
    render(<VoiceCallButton readiness={READY} failed={false} onStart={onStart} setUpHref={null} />);
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAttribute("data-tour", "chat-voice-call");
    fireEvent.click(button);
    expect(onStart).toHaveBeenCalledOnce();
  });

  it("is drawn like Send when it stands in Send's place (#2301)", () => {
    const { rerender } = render(
      <VoiceCallButton readiness={READY} failed={false} onStart={vi.fn()} setUpHref={null} />,
    );
    const quiet = screen.getByRole("button", { name: NAME }).className;

    rerender(
      <VoiceCallButton
        readiness={READY}
        failed={false}
        onStart={vi.fn()}
        setUpHref={null}
        prominent
      />,
    );

    expect(screen.getByRole("button", { name: NAME }).className).not.toBe(quiet);
    expect(screen.getByRole("button", { name: NAME }).className).toContain("active:scale-90");
  });

  it("says, beside a draft being tested, that a call runs the published version", () => {
    render(
      <VoiceCallButton
        readiness={READY}
        failed={false}
        onStart={vi.fn()}
        setUpHref={null}
        publishedOnly
      />,
    );

    expect(screen.getByRole("button", { name: NAME })).toHaveAttribute(
      "title",
      expect.stringContaining("published version"),
    );
  });

  it("can be held off while something else is under way", () => {
    render(
      <VoiceCallButton
        readiness={READY}
        failed={false}
        disabled
        onStart={vi.fn()}
        setUpHref={null}
      />,
    );
    expect(screen.getByRole("button", { name: NAME })).toBeDisabled();
  });

  it.each([
    ["not_offered", "This agent's voice model is no longer offered"],
    ["no_key", "This agent's voice has no key"],
  ] as const)("is crossed out with the reason when %s", (reason, title) => {
    const onStart = vi.fn();
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: reason }}
        failed={false}
        onStart={onStart}
        setUpHref={null}
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(expect.stringContaining(title));
    fireEvent.click(button);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("is offered for an agent with no voice too, saying calls are off and where to turn them on", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_voice" }}
        failed={false}
        onStart={vi.fn()}
        setUpHref="/agents/a1#agent-voice"
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      expect.stringContaining("Calls aren't turned on for this agent"),
    );
    fireEvent.focus(button);
    expect(screen.getByRole("link", { name: "Open in the Agent Builder" })).toHaveAttribute(
      "href",
      "/agents/a1#agent-voice",
    );
  });

  it("is not there at all while the agent's answer loads, so it does not flash", () => {
    const { container } = render(
      <VoiceCallButton readiness={null} failed={false} onStart={vi.fn()} setUpHref={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("says it could not check when an unavailable answer names no reason", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: null }}
        failed={false}
        onStart={vi.fn()}
        setUpHref={null}
      />,
    );
    expect(screen.getByRole("button", { name: NAME })).toHaveAccessibleDescription(
      expect.stringContaining("Could not check"),
    );
  });

  it("says when readiness could not be read rather than hiding the button", () => {
    render(<VoiceCallButton readiness={null} failed onStart={vi.fn()} setUpHref={null} />);
    expect(screen.getByRole("button", { name: NAME })).toHaveAccessibleDescription(
      expect.stringContaining("Could not check"),
    );
  });

  it("links somebody who can fix it to the Builder, and a press hands the link focus", async () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_key" }}
        failed={false}
        onStart={vi.fn()}
        setUpHref="/agents/a1#agent-voice"
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    fireEvent.click(button);
    const link = screen.getByRole("link", { name: "Open in the Agent Builder" });
    await vi.waitFor(() => expect(link).toHaveFocus());
    // Focus moving into the popover does not close it.
    fireEvent.blur(button, { relatedTarget: link });
    expect(link).toBeInTheDocument();
  });

  it("tells everybody else whom to ask", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_voice" }}
        failed={false}
        onStart={vi.fn()}
        setUpHref={null}
      />,
    );
    fireEvent.focus(screen.getByRole("button", { name: NAME }));
    expect(
      screen.getByText("Ask someone who can edit this agent to set it up.", { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("names nobody to ask when it could not check", () => {
    render(<VoiceCallButton readiness={null} failed onStart={vi.fn()} setUpHref="/agents/a1" />);
    fireEvent.focus(screen.getByRole("button", { name: NAME }));
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("Ask someone who can edit this agent to set it up.")).toBeNull();
  });

  it("explains itself on hover, on keyboard focus and on a press", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_key" }}
        failed={false}
        onStart={vi.fn()}
        setUpHref={null}
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    const popover = () =>
      screen.queryByText("Choose a key on its Voice card.", {
        selector: "p",
      });

    vi.useFakeTimers();
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    expect(popover()).toBeInTheDocument();
    // A moment to cross into the popover, where the pointer keeps it open.
    fireEvent.pointerLeave(button, { pointerType: "mouse" });
    fireEvent.pointerEnter(popover()!.parentElement!, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(500));
    expect(popover()).toBeInTheDocument();
    fireEvent.pointerLeave(popover()!.parentElement!, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(500));
    expect(popover()).toBeNull();
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    fireEvent.pointerLeave(button, { pointerType: "mouse" });
    act(() => vi.advanceTimersByTime(500));
    expect(popover()).toBeNull();
    // A finger lifting off the open popover does not close it.
    fireEvent.click(button);
    fireEvent.pointerLeave(popover()!.parentElement!, { pointerType: "touch" });
    act(() => vi.advanceTimersByTime(500));
    expect(popover()).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    vi.useRealTimers();

    // A touch neither opens nor closes it by passing over.
    fireEvent.pointerEnter(button, { pointerType: "touch" });
    fireEvent.pointerLeave(button, { pointerType: "touch" });
    expect(popover()).toBeNull();

    fireEvent.focus(button);
    expect(popover()).toBeInTheDocument();
    fireEvent.blur(button);
    expect(popover()).toBeNull();

    // A press focuses the button too; that focus does not open it, the click does.
    fireEvent.pointerDown(button);
    fireEvent.focus(button);
    expect(popover()).toBeNull();
    fireEvent.click(button);
    expect(popover()).toBeInTheDocument();
    // A second press leaves it open; Escape or a press elsewhere closes it.
    fireEvent.click(button);
    expect(popover()).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(popover()).toBeNull();
  });
});
