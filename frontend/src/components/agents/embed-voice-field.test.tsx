import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmbedVoiceField } from "./embed-voice-field";

/**
 * The switch that lets strangers call the agent (#54).
 *
 * What it pins is the honesty of the offer: on only where a call would start,
 * never locking an embed already on, and saying what a visitor's call leaves out.
 */

type Props = Parameters<typeof EmbedVoiceField>[0];

function field(overrides: Partial<Props> = {}) {
  const props: Props = {
    name: "w",
    value: false,
    disabled: false,
    available: true,
    unchecked: false,
    wasOn: false,
    onChange: vi.fn(),
    ...overrides,
  };
  return { ...render(<EmbedVoiceField {...props} />), props };
}

describe("EmbedVoiceField", () => {
  it("offers the switch where a call would start", async () => {
    const { props } = field();

    await userEvent.click(screen.getByRole("switch", { name: "Voice calls" }));

    expect(props.onChange).toHaveBeenCalledWith(true);
  });

  it("is locked with the reason where none would, unless it is already on", () => {
    const { rerender } = field({ available: false });

    expect(screen.getByRole("switch", { name: "Voice calls" })).toBeDisabled();
    expect(screen.getByText(/need the organization's voice switch on/)).toBeInTheDocument();

    rerender(
      <EmbedVoiceField
        name="w"
        value
        disabled={false}
        available={false}
        unchecked={false}
        wasOn
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("switch", { name: "Voice calls" })).toBeEnabled();
    expect(screen.getByText(/Visitors see no call button/)).toBeInTheDocument();
  });

  it("says when the agent's readiness could not be read rather than locking silently", () => {
    field({ available: null, unchecked: true });

    expect(screen.getByRole("switch", { name: "Voice calls" })).toBeDisabled();
    expect(screen.getByText(/can't be checked right now/)).toBeInTheDocument();
  });

  it("says nothing while the readiness is still on its way", () => {
    field({ available: null });

    expect(screen.queryByText(/can't be checked right now/)).toBeNull();
    expect(screen.queryByText(/need the organization's voice switch on/)).toBeNull();
  });

  it("says visitors cannot approve, so gated tools are left out", () => {
    field({ value: true, wasOn: true });

    expect(screen.getByText(/tools that need approval are left out/)).toBeInTheDocument();
  });

  it("is locked while the form is saving", () => {
    field({ disabled: true, wasOn: true });

    expect(screen.getByRole("switch", { name: "Voice calls" })).toBeDisabled();
  });
});
