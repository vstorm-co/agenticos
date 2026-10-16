import { fireEvent, render, screen } from "@testing-library/react";
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
  minutes_left: 540,
  unavailable_capabilities: [],
};

const NAME = "Start a voice call";

describe("VoiceCallButton", () => {
  it("starts a call when the agent is ready", () => {
    const onStart = vi.fn();
    render(<VoiceCallButton readiness={READY} failed={false} onStart={onStart} canSetUp={false} />);
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAttribute("data-tour", "chat-voice-call");
    fireEvent.click(button);
    expect(onStart).toHaveBeenCalledOnce();
  });

  it("can be held off while something else is under way", () => {
    render(
      <VoiceCallButton
        readiness={READY}
        failed={false}
        disabled
        onStart={vi.fn()}
        canSetUp={false}
      />,
    );
    expect(screen.getByRole("button", { name: NAME })).toBeDisabled();
  });

  it.each([
    ["no_voice", "This agent has no voice set up"],
    ["not_offered", "This agent's voice model is no longer offered"],
    ["no_key", "This agent's voice has no key"],
    ["minutes_exhausted", "No call minutes left this month"],
  ] as const)("is crossed out with the reason when %s", (reason, title) => {
    const onStart = vi.fn();
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: reason }}
        failed={false}
        onStart={onStart}
        canSetUp={false}
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(expect.stringContaining(title));
    fireEvent.click(button);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("is not there at all while the agent's answer loads, so it does not flash", () => {
    const { container } = render(
      <VoiceCallButton readiness={null} failed={false} onStart={vi.fn()} canSetUp={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["org_off", "not_in_chat"] as const)(
    "is not there at all when the organization has calls off (%s)",
    (reason) => {
      const { container } = render(
        <VoiceCallButton
          readiness={{ ...READY, available: false, unavailable: reason }}
          failed={false}
          onStart={vi.fn()}
          canSetUp
        />,
      );
      expect(container).toBeEmptyDOMElement();
    },
  );

  it("says it could not check when an unavailable answer names no reason", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: null }}
        failed={false}
        onStart={vi.fn()}
        canSetUp={false}
      />,
    );
    expect(screen.getByRole("button", { name: NAME })).toHaveAccessibleDescription(
      expect.stringContaining("Could not check"),
    );
  });

  it("says when readiness could not be read rather than hiding the button", () => {
    render(<VoiceCallButton readiness={null} failed onStart={vi.fn()} canSetUp={false} />);
    expect(screen.getByRole("button", { name: NAME })).toHaveAccessibleDescription(
      expect.stringContaining("Could not check"),
    );
  });

  it("tells somebody who can fix it where to", () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_key" }}
        failed={false}
        onStart={vi.fn()}
        canSetUp
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    expect(button).toHaveAccessibleDescription(
      expect.stringContaining("You can set this up in Voice settings."),
    );
    fireEvent.focus(button);
    expect(
      screen.getByText("You can set this up in Voice settings.", { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("explains itself on hover, on keyboard focus and on a press", async () => {
    render(
      <VoiceCallButton
        readiness={{ ...READY, available: false, unavailable: "no_voice" }}
        failed={false}
        onStart={vi.fn()}
        canSetUp={false}
      />,
    );
    const button = screen.getByRole("button", { name: NAME });
    const popover = () =>
      screen.queryByText("Its Voice card has no voice conversation model.", {
        selector: "p",
      });

    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    expect(popover()).toBeInTheDocument();
    fireEvent.pointerLeave(button, { pointerType: "mouse" });
    expect(popover()).toBeNull();

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
    fireEvent.click(button);
    expect(popover()).toBeNull();
  });
});
