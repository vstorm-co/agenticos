import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VoiceControls } from "./voice-controls";

function setup(pushToTalk = false, muted = false) {
  const props = {
    muted,
    pushToTalk,
    onMutedChange: vi.fn(),
    onPushToTalkChange: vi.fn(),
    onPress: vi.fn(),
    onEnd: vi.fn(),
  };
  const view = render(<VoiceControls {...props} />);
  return { props, view };
}

describe("VoiceControls", () => {
  it("mutes, switches to push-to-talk and ends", () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    fireEvent.click(screen.getByRole("switch", { name: "Push to talk" }));
    fireEvent.click(screen.getByRole("button", { name: "End call" }));
    expect(props.onMutedChange).toHaveBeenCalledWith(true);
    expect(props.onPushToTalkChange).toHaveBeenCalledWith(true);
    expect(props.onEnd).toHaveBeenCalledOnce();
  });

  it("unmutes a muted microphone", () => {
    const { props } = setup(false, true);
    const button = screen.getByRole("button", { name: "Unmute" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(props.onMutedChange).toHaveBeenCalledWith(false);
  });

  it("talks while the button is held", () => {
    const { props } = setup(true);
    const hold = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(hold);
    fireEvent.pointerUp(hold);
    // Leaving the button after letting go does not let go twice.
    fireEvent.pointerLeave(hold);
    expect(props.onPress.mock.calls).toEqual([[true], [false]]);
  });

  it("lets go when the pointer slides off the held button", () => {
    const { props } = setup(true);
    const hold = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(hold);
    fireEvent.pointerLeave(hold);
    expect(props.onPress.mock.calls).toEqual([[true], [false]]);
  });

  it("talks while Space is held, but not while typing", () => {
    const { props } = setup(true);
    fireEvent.keyDown(window, { key: " ", code: "Space" });
    fireEvent.keyDown(window, { key: " ", code: "Space", repeat: true });
    fireEvent.keyDown(window, { key: "a", code: "KeyA" });
    fireEvent.keyUp(window, { key: "a", code: "KeyA" });
    fireEvent.keyUp(window, { key: " ", code: "Space" });
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: " ", code: "Space" });
    fireEvent.keyUp(input, { key: " ", code: "Space" });
    const editor = document.createElement("div");
    editor.contentEditable = "true";
    Object.defineProperty(editor, "isContentEditable", { value: true });
    document.body.appendChild(editor);
    fireEvent.keyDown(editor, { key: " ", code: "Space" });
    expect(props.onPress.mock.calls).toEqual([[true], [false]]);
    input.remove();
    editor.remove();
  });

  it("stops listening for Space once push-to-talk is off", () => {
    const { props, view } = setup(true);
    view.rerender(<VoiceControls {...props} pushToTalk={false} />);
    fireEvent.keyDown(window, { key: " ", code: "Space" });
    expect(props.onPress).not.toHaveBeenCalled();
  });

  it.each(["pointerCancel", "lostPointerCapture"] as const)(
    "lets go when the browser takes the pointer away (%s)",
    (event) => {
      const { props } = setup(true);
      const hold = screen.getByRole("button", { name: "Hold to talk" });
      fireEvent.pointerDown(hold);
      fireEvent[event](hold);
      expect(props.onPress.mock.calls).toEqual([[true], [false]]);
    },
  );

  it("lets go of Space even when focus moved into a text field meanwhile", () => {
    const { props } = setup(true);
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(window, { key: " ", code: "Space" });
    input.focus();
    fireEvent.keyUp(input, { key: " ", code: "Space" });
    expect(props.onPress.mock.calls).toEqual([[true], [false]]);
    input.remove();
  });

  it("offers no hold button when hands-free", () => {
    setup(false);
    expect(screen.queryByRole("button", { name: "Hold to talk" })).toBeNull();
  });
});
