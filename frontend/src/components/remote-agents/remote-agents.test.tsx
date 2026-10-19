import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterRemoteAgentDialog } from "./register-remote-agent-dialog";
import { RemoteAgentList } from "./remote-agent-list";
import { ApiError } from "@/lib/api-error";
import type { ExternalAgent } from "@/types/external-agents";

const { toast } = vi.hoisted(() => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("sonner", () => ({ toast }));

vi.mock("@/hooks", () => ({
  useSecrets: () => ({
    secrets: [
      { id: "s-1", name: "Reviewer key", kind: "api_key", purpose: "a2a", hint: "abcd" },
      { id: "s-2", name: "AWS", kind: "aws", purpose: null, hint: "x" },
      { id: "s-3", name: "Loose key", kind: "api_key", purpose: null, hint: "y" },
    ],
    create: { mutate: vi.fn(), isPending: false },
  }),
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));

function agent(overrides: Partial<ExternalAgent> = {}): ExternalAgent {
  return {
    id: "ea-1",
    slug: "contract-reviewer",
    name: "Contract Reviewer",
    description: "Reads contracts.",
    card_url: "https://agents.example.com",
    endpoint_url: "https://agents.example.com/a2a/reviewer",
    secret_id: "s-1",
    skills: [{ id: "review", name: "Review", description: "Review a contract" }],
    can_manage: true,
    created_at: "2026-10-17T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RemoteAgentList", () => {
  it("shows what the card said, where the agent answers, and that it sends a key", () => {
    render(<RemoteAgentList agents={[agent()]} onRefresh={vi.fn()} onRemove={vi.fn()} />);

    expect(screen.getByText("Contract Reviewer")).toBeVisible();
    expect(screen.getByText("Reads contracts.")).toBeVisible();
    expect(screen.getByText("Answers on agents.example.com")).toBeVisible();
    expect(screen.getByText("Review")).toBeVisible();
    expect(screen.getByText("Sends a key")).toBeVisible();
  });

  it("reads a card again, and says when it could not", async () => {
    const onRefresh = vi.fn().mockResolvedValueOnce(agent()).mockRejectedValueOnce(new Error("x"));
    render(<RemoteAgentList agents={[agent()]} onRefresh={onRefresh} onRemove={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Read Contract Reviewer's card again" });
    await userEvent.click(button);
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    await userEvent.click(button);
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("removes one after asking, and reports a refusal", async () => {
    const onRemove = vi.fn().mockRejectedValue(new Error("refused"));
    render(
      <RemoteAgentList
        agents={[
          agent({ description: "", skills: [], secret_id: null, endpoint_url: "not a url" }),
        ]}
        onRefresh={vi.fn()}
        onRemove={onRemove}
      />,
    );

    expect(screen.getByText("Answers on not a url")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove Contract Reviewer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));

    expect(onRemove).toHaveBeenCalledWith("ea-1");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("keeps one it was asked to remove when the question is cancelled", async () => {
    const onRemove = vi.fn();
    render(<RemoteAgentList agents={[agent()]} onRefresh={vi.fn()} onRemove={onRemove} />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Contract Reviewer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(onRemove).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("offers no controls on a registration this person may not change", () => {
    render(
      <RemoteAgentList
        agents={[agent({ can_manage: false })]}
        onRefresh={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("RegisterRemoteAgentDialog", () => {
  function mount(onSubmit = vi.fn().mockResolvedValue(agent())) {
    const onOpenChange = vi.fn();
    render(<RegisterRemoteAgentDialog open onOpenChange={onOpenChange} onSubmit={onSubmit} />);
    return { onSubmit, onOpenChange };
  }

  it("registers by the card's address, with a handle and a key", async () => {
    const { onSubmit, onOpenChange } = mount();

    expect(screen.getByRole("button", { name: "Register an agent" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Agent card address"), "https://agents.example.com");
    await userEvent.type(screen.getByLabelText("Handle"), "reviewer");
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: /Reviewer key/ }));
    await userEvent.click(screen.getByRole("button", { name: "Register an agent" }));

    expect(onSubmit).toHaveBeenCalledWith({
      card_url: "https://agents.example.com",
      slug: "reviewer",
      secret_id: "s-1",
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(toast.success).toHaveBeenCalledWith("Registered Contract Reviewer");
  });

  it("sends neither a handle nor a key nobody chose", async () => {
    const { onSubmit } = mount();

    await userEvent.type(screen.getByLabelText("Agent card address"), "https://agents.example.com");
    await userEvent.click(screen.getByRole("button", { name: "Register an agent" }));

    expect(onSubmit).toHaveBeenCalledWith({ card_url: "https://agents.example.com" });
  });

  it("puts a card that could not be read on the address field", async () => {
    mount(
      vi
        .fn()
        .mockRejectedValue(
          new ApiError(400, "That address does not answer with an A2A agent card", {}),
        ),
    );

    await userEvent.type(screen.getByLabelText("Agent card address"), "https://example.com");
    await userEvent.click(screen.getByRole("button", { name: "Register an agent" }));

    expect(await screen.findByText(/does not answer with an A2A agent card/)).toBeVisible();
  });

  it("marks a taken handle on the handle", async () => {
    mount(vi.fn().mockRejectedValue(new ApiError(409, "Handle taken", {})));

    await userEvent.type(screen.getByLabelText("Agent card address"), "https://example.com");
    await userEvent.click(screen.getByRole("button", { name: "Register an agent" }));

    expect(await screen.findByText("Handle taken")).toBeVisible();
  });

  it("closes on Escape like any dialog", async () => {
    const { onOpenChange } = mount();
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("forgets what was typed when it is closed", async () => {
    const { onOpenChange } = mount();
    await userEvent.type(screen.getByLabelText("Agent card address"), "https://x.example");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
