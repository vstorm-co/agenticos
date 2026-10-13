import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmbedDictationField } from "./embed-dictation-field";
import type { EmbedDictation } from "@/types/embeds";

/**
 * The voice choice on a hosted page and a widget (#1797).
 *
 * What it has to get right is the one refusal the backend makes: `server` is
 * refused when it is switched on while no provider answers for the agent - and
 * only then, so a page already on `server` is never locked out of its own form.
 */

const onChange = vi.fn();

function field(
  value: EmbedDictation,
  serverAvailable: boolean | null,
  wasServer = false,
  disabled = false,
) {
  render(
    <EmbedDictationField
      name="test-dictation"
      value={value}
      disabled={disabled}
      serverAvailable={serverAvailable}
      wasServer={wasServer}
      onChange={onChange}
    />,
  );
}

beforeEach(() => onChange.mockClear());

describe("the voice choice", () => {
  it("says where the audio goes for each choice", () => {
    field("off", true);

    expect(screen.getByText(/sends the audio to its vendor/)).toBeInTheDocument();
    expect(screen.getByText(/on the organization's bill/)).toBeInTheDocument();
  });

  it("offers server where a provider answers, and carries the choice", async () => {
    field("off", true);

    await userEvent.click(screen.getByRole("radio", { name: /Server/ }));

    expect(onChange).toHaveBeenCalledWith("server");
  });

  it("disables server with the reason when nothing would answer it", () => {
    field("off", false);

    expect(screen.getByRole("radio", { name: /Server/ })).toBeDisabled();
    expect(screen.getByText(/needs a speech-to-text provider/)).toBeInTheDocument();
  });

  it("keeps server selectable on a page already on it, and says visitors see no microphone", () => {
    field("server", false, true);

    expect(screen.getByRole("radio", { name: /Server/ })).toBeEnabled();
    expect(screen.getByText(/visitors see no microphone/)).toBeInTheDocument();
  });

  it("waits for the agent's readiness before offering server, saying nothing yet", () => {
    field("off", null);

    expect(screen.getByRole("radio", { name: /Server/ })).toBeDisabled();
    expect(screen.queryByText(/needs a speech-to-text provider/)).toBeNull();
  });

  it("locks every choice while the form is saving", () => {
    field("off", true, false, true);

    expect(screen.getByRole("radio", { name: /Browser/ })).toBeDisabled();
  });
});
