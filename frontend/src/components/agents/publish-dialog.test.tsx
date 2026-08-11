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

function environment(name: string, versionNumber: number, isDefault: boolean): AgentEnvironment {
  return {
    id: `${name}-id`,
    agent_id: "a-1",
    name,
    version_id: `v${versionNumber}-id`,
    version: versionNumber,
    is_default: isDefault,
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
        "The first publish creates the production environment pointing at v1, and the agent starts answering with it immediately.",
      ),
    ).toBeInTheDocument();
  });

  it("names the environment that moves and the pinned ones that do not", () => {
    render(
      <PublishDialog
        open
        onOpenChange={vi.fn()}
        version={13}
        environments={[
          environment("production", 12, true),
          environment("dev", 12, false),
          environment("client-a", 9, false),
        ]}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText("production moves to v13 the moment you publish.")).toBeInTheDocument();
    // Pinned environments keep the version somebody chose for them - each is
    // named with the version it stays on, not the one being published.
    expect(
      screen.getByText("dev stays on v12 - promoting it is a separate step."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("client-a stays on v9 - promoting it is a separate step."),
    ).toBeInTheDocument();
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
