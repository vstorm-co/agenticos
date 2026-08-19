import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PublishDialog } from "./publish-dialog";
import type { AgentEnvironment } from "@/types/agents";

/**
 * Publish saying what it moves before it does it (#519).
 *
 * Publishing repoints exactly one environment - the default - and the first
 * publish creates it. A pinned environment stays where somebody put it, which
 * is the fact this dialog exists to surface: the agent with a client held back
 * on v9 is exactly the one where "Publish" hides the most.
 */

function environment(
  name: string,
  versionNumber: number,
  isDefault: boolean,
  tracksLatest = false,
): AgentEnvironment {
  return {
    id: `${name}-id`,
    agent_id: "a-1",
    name,
    version_id: `v${versionNumber}-id`,
    version: versionNumber,
    is_default: isDefault,
    tracks_latest: tracksLatest,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    created_at: "2026-07-30T10:00:00Z",
  };
}

describe("the publish dialog", () => {
  it("says the first publish creates production and goes live at once", () => {
    render(
      <PublishDialog
        open
        onOpenChange={vi.fn()}
        version={1}
        environments={[]}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Publish v1?" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "This is the first publish, so it creates production on v1 - the agent has to have somewhere to run.",
      ),
    ).toBeInTheDocument();
  });

  it("names what moves and what does not, the default included", () => {
    // Publishing mints a version and moves only what asked to be moved. The
    // question worth answering before the click is what changes for the people
    // using this agent - and for most agents the answer is nothing.
    render(
      <PublishDialog
        open
        onOpenChange={vi.fn()}
        version={13}
        environments={[
          environment("production", 12, true),
          environment("dev", 12, false, true),
          environment("client-a", 9, false),
        ]}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText("production stays on v12 until you promote.")).toBeInTheDocument();
    expect(screen.getByText("dev follows every publish, so it moves to v13.")).toBeInTheDocument();
    expect(screen.getByText("client-a stays on v9 until you promote.")).toBeInTheDocument();
  });

  it("publishes on confirm and closes on cancel", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <PublishDialog
        open
        onOpenChange={onOpenChange}
        version={2}
        environments={[environment("production", 1, true)]}
        onConfirm={onConfirm}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("disables both buttons while the publish is in flight", () => {
    render(
      <PublishDialog
        open
        onOpenChange={vi.fn()}
        version={2}
        environments={[]}
        publishing
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
