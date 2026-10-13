import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { DictationUnavailable } from "./dictation-unavailable";

beforeAll(() => {
  // jsdom has no PointerEvent, and the popover tells a mouse from a finger by
  // `pointerType` - a tap fires the same enter as a hover.
  if (typeof window.PointerEvent === "undefined") {
    class PointerEvent extends MouseEvent {
      readonly pointerType: string;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerType = init.pointerType ?? "";
      }
    }
    vi.stubGlobal("PointerEvent", PointerEvent);
  }
});

function show(
  why: "not_ready" | "no_agent" = "not_ready",
  voiceSettingsHref: string | null = null,
  agentVoiceHref: string | null = null,
) {
  const onExplain = vi.fn();
  render(
    <DictationUnavailable
      why={why}
      voiceSettingsHref={voiceSettingsHref}
      agentVoiceHref={agentVoiceHref}
      onExplain={onExplain}
    />,
  );
  return { onExplain, button: screen.getByRole("button", { name: "Voice input" }) };
}

describe("DictationUnavailable", () => {
  it("is the crossed-out mic: still focusable, named as the mic, and saying why", () => {
    const { button } = show();

    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(button.querySelector("svg")!.getAttribute("class")).toContain("lucide-mic-off");
    expect(button).toHaveAccessibleDescription(
      "Dictation isn't set up yet. This organization transcribes on its own server, and no speech-to-text model is chosen for it or for this agent.",
    );
  });

  it("asks for an agent when there is none", () => {
    const { button } = show("no_agent");

    expect(button).toHaveAccessibleDescription(/^Pick an agent first\./);
    fireEvent.focus(button);
    expect(screen.getByRole("dialog")).toHaveTextContent("Pick an agent first.");
    expect(screen.queryByText("Ask an admin to set it up.")).not.toBeInTheDocument();
  });

  it("opens the explanation under the composer on a click, not a popover", () => {
    const { button, onExplain } = show();

    fireEvent.pointerDown(button);
    fireEvent.focus(button);
    fireEvent.click(button);

    expect(onExplain).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("explains in a popover to a keyboard arriving, and tells a member to ask an admin", () => {
    const { button } = show();

    act(() => button.focus());

    const popover = screen.getByRole("dialog");
    expect(popover).toHaveTextContent("Dictation isn't set up yet.");
    expect(popover).toHaveTextContent("Ask an admin to set it up.");
    expect(button).toHaveFocus();

    fireEvent.blur(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links an org:settings holder to the Voice card", () => {
    const { button } = show("not_ready", "/orgs/o1/members#org-voice");

    fireEvent.focus(button);

    expect(screen.getByRole("link", { name: "Open Voice settings" })).toHaveAttribute(
      "href",
      "/orgs/o1/members#org-voice",
    );
    expect(screen.queryByText("Ask an admin to set it up.")).not.toBeInTheDocument();
  });

  it("links an agent editor to this agent's Voice card, beside the organization's", () => {
    const { button } = show("not_ready", "/orgs/o1/members#org-voice", "/agents/a1#agent-voice");

    fireEvent.focus(button);

    expect(screen.getByRole("link", { name: "Set one for this agent" })).toHaveAttribute(
      "href",
      "/agents/a1#agent-voice",
    );
    expect(screen.getByRole("link", { name: "Open Voice settings" })).toBeInTheDocument();
  });

  it("links an agent editor without org settings to the agent alone", () => {
    const { button } = show("not_ready", null, "/agents/a1#agent-voice");

    fireEvent.focus(button);

    expect(screen.getByRole("link", { name: "Set one for this agent" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Voice settings" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ask an admin to set it up.")).not.toBeInTheDocument();
  });

  it("opens on a mouse hover and closes when it leaves, but not for a finger", () => {
    const { button } = show();

    fireEvent.pointerEnter(button, { pointerType: "touch" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.pointerLeave(button, { pointerType: "touch" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.pointerLeave(button, { pointerType: "mouse" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
