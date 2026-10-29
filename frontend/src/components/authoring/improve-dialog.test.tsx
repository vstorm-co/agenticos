import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthoringEstimate } from "@/types/authoring";
import { ImproveDialog } from "./improve-dialog";

const helpers = vi.hoisted(() => ({ alternatives: true }));
vi.mock("@/hooks/use-agents", () => ({
  useAgentsOfKind: () => ({
    agents: [
      {
        id: "seeded",
        name: "Authoring assistant",
        system_key: "improver",
        status: "published",
        current_version_id: "v0",
        published_model: { label: "gpt-4.1-mini" },
      },
      ...(helpers.alternatives
        ? [
            {
              id: "helper",
              name: "Selected helper",
              system_key: null,
              status: "published",
              current_version_id: "v1",
              published_model: null,
            },
          ]
        : []),
    ],
    isLoading: false,
    error: null,
  }),
}));

function quote(overrides: Partial<AuthoringEstimate> = {}): AuthoringEstimate {
  return {
    runs: 22,
    rated_down: 6,
    calls: 1,
    estimate_usd: "0.04",
    affordable: true,
    reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  helpers.alternatives = true;
});

describe("ImproveDialog", () => {
  it("shows what it would read and cost, and starts on the second click", async () => {
    const estimate = vi.fn().mockResolvedValue(quote());
    const start = vi.fn().mockResolvedValue({});
    const onOpenChange = vi.fn();
    render(
      <ImproveDialog
        kind="improve"
        estimate={estimate}
        start={start}
        onOpenChange={onOpenChange}
      />,
    );
    expect(estimate).toHaveBeenCalledWith({ kind: "improve", window_days: 30 });
    expect(await screen.findByText(/It will read 22 runs, 6 rated down/)).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(start).toHaveBeenCalledWith({ kind: "improve", window_days: 30 });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("explains why it cannot start", async () => {
    render(
      <ImproveDialog
        kind="verify"
        estimate={vi.fn().mockResolvedValue(quote({ reason: "no_draft_change" }))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "The draft is the same as the published version, so there is nothing to verify.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("refuses past the budget and shows a refusal", async () => {
    const { unmount } = render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockResolvedValue(quote({ affordable: false }))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "That is more than the assistant's monthly budget or the organization's has left.",
      ),
    ).toBeInTheDocument();
    unmount();
    render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockRejectedValue(new Error("No improver"))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("No improver");
  });

  it("keeps the dialog open when starting is refused, and cancels", async () => {
    const onOpenChange = vi.fn();
    render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockResolvedValue(quote())}
        start={vi.fn().mockRejectedValue(new Error("Out of budget"))}
        onOpenChange={onOpenChange}
      />,
    );
    await screen.findByText(/It will read/);
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Out of budget");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("drops an estimate that arrives after the dialog closed", async () => {
    let resolve: (value: AuthoringEstimate) => void = () => undefined;
    const estimate = vi.fn(
      () =>
        new Promise<AuthoringEstimate>((done) => {
          resolve = done;
        }),
    );
    const { unmount } = render(
      <ImproveDialog kind="improve" estimate={estimate} start={vi.fn()} onOpenChange={vi.fn()} />,
    );
    unmount();
    resolve(quote());
    await Promise.resolve();
    expect(screen.queryByText(/It will read/)).toBeNull();
  });
});

it("re-estimates after changing the improver and starts with the selected helper", async () => {
  const estimate = vi.fn().mockResolvedValue(quote());
  const start = vi.fn().mockResolvedValue({});
  render(<ImproveDialog kind="improve" estimate={estimate} start={start} onOpenChange={vi.fn()} />);
  await screen.findByText(/It will read/);
  await userEvent.click(screen.getByText("Authoring assistant"));
  await userEvent.click(screen.getByRole("combobox", { name: "Run with" }));
  await userEvent.click(screen.getByRole("option", { name: "Selected helper" }));
  await waitFor(() =>
    expect(estimate).toHaveBeenLastCalledWith({
      kind: "improve",
      window_days: 30,
      improver_agent_id: "helper",
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  expect(start).toHaveBeenCalledWith({
    kind: "improve",
    window_days: 30,
    improver_agent_id: "helper",
  });
});

it("names the default helper and offers no choice when it is the only one", async () => {
  helpers.alternatives = false;
  render(
    <ImproveDialog
      kind="improve"
      estimate={vi.fn().mockResolvedValue(quote())}
      start={vi.fn()}
      onOpenChange={vi.fn()}
    />,
  );
  await screen.findByText(/It will read/);
  await userEvent.click(screen.getByText("Authoring assistant"));
  expect(screen.queryByRole("combobox", { name: "Run with" })).toBeNull();
  expect(screen.getByText(/Runs with Authoring assistant · gpt-4\.1-mini/)).toBeInTheDocument();
});
