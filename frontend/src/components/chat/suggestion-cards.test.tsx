import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuggestionCards } from "./suggestion-cards";
import type { Suggestion } from "@/lib/suggestions-api";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";
import type { User } from "@/types";

/**
 * What the night proposed, above the starter agent's empty chat (#2301): each
 * kind does its own thing when taken, and "Not now" declines it for good.
 */

const state = vi.hoisted(() => ({
  suggestions: [] as Suggestion[],
  accept: vi.fn(),
  dismiss: vi.fn(),
  dialogs: [] as (TriggerTemplate | undefined)[],
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({
    suggestions: state.suggestions,
    accept: state.accept,
    dismiss: state.dismiss,
  }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
vi.mock("@/hooks", () => ({
  useMcpCatalog: () => ({
    servers: [{ key: "github", name: "GitHub", icon: "github", url: null }],
  }),
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({
    initialTemplate,
    onOpenChange,
    onCreated,
  }: {
    initialTemplate?: TriggerTemplate;
    onOpenChange: (open: boolean) => void;
    onCreated?: () => void;
  }) => {
    state.dialogs.push(initialTemplate);
    return (
      <div role="dialog">
        <button type="button" onClick={() => onCreated?.()}>
          create
        </button>
        <button type="button" onClick={() => onOpenChange(false)}>
          close
        </button>
      </div>
    );
  },
}));

function suggestion(kind: Suggestion["kind"], payload: Record<string, unknown>): Suggestion {
  return {
    id: `s-${kind}`,
    kind,
    status: "open",
    title: `Title ${kind}`,
    detail: `Detail ${kind}`,
    payload,
    created_at: "2026-10-22T05:00:00Z",
  };
}

beforeEach(() => {
  state.suggestions = [];
  state.accept.mockReset().mockResolvedValue({});
  state.dismiss.mockReset().mockResolvedValue({});
  state.dialogs = [];
  toastSuccess.mockReset();
  toastError.mockReset();
  useArchitectAskStore.setState({ request: null });
  useAuthStore.setState({ user: { id: "u-1", job_title: null } as User });
});

describe("SuggestionCards", () => {
  it("opens a finding where it lives and marks it done", async () => {
    state.suggestions = [
      suggestion("finding", { server: "github", account: null, url: "https://github.com/o/r/1" }),
      { ...suggestion("finding", { server: null, account: null, url: null }), id: "s-bare" },
    ];
    render(<SuggestionCards agentId={null} />);

    const links = screen.getAllByRole("link", { name: "Open" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://github.com/o/r/1");
    expect(links[0]).toHaveAttribute("target", "_blank");
    await userEvent.click(screen.getAllByRole("button", { name: "Done" })[0]!);
    await waitFor(() => expect(state.accept).toHaveBeenCalledWith("s-finding"));
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("offers one, what cannot wait first, and leaves the rest to the inbox", () => {
    const routine = suggestion("routine", { prompt: "p" });
    const urgent = {
      ...suggestion("finding", { server: "github", account: null, url: null }),
      urgent: true,
    };
    state.suggestions = [routine, urgent];
    render(<SuggestionCards agentId={null} className="max-w-none" />);

    const cards = screen.getAllByRole("group");
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual(["Title finding"]);
    expect(cards[0]).toHaveTextContent("Urgent");
    expect(screen.getByRole("link", { name: "1 more in your inbox" })).toHaveAttribute(
      "href",
      "/inbox",
    );
  });

  it("draws nothing when nothing was proposed", () => {
    const { container } = render(<SuggestionCards agentId="a-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("opens the routine dialog filled in with the request and its cadence", async () => {
    state.suggestions = [suggestion("routine", { prompt: "Summarise sales", cron: "0 7 * * 1" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Set it up" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(state.dialogs.at(-1)).toMatchObject({
      prompt: "Summarise sales",
      suggested_cadence: { schedule_kind: "cron", cron_expression: "0 7 * * 1" },
    });
    // Codex on #2324: opening the dialog takes nothing - only a routine that exists does.
    expect(state.accept).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "create" }));
    await waitFor(() => expect(state.accept).toHaveBeenCalledWith("s-routine"));
  });

  it("leaves the routine suggestion open when its dialog is closed unsaved", async () => {
    state.suggestions = [suggestion("routine", { prompt: "Summarise sales" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Set it up" }));
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(state.accept).not.toHaveBeenCalled();
  });

  it("gives a routine with no cadence a weekly one to change", async () => {
    state.suggestions = [suggestion("routine", { prompt: "Check the inbox" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Set it up" }));

    expect(state.dialogs.at(-1)?.suggested_cadence).toEqual({
      schedule_kind: "cron",
      cron_expression: "0 8 * * 1",
    });
  });

  it("asks the Architect to build an agent for the request", async () => {
    state.suggestions = [suggestion("agent", { request: "Answer refund emails" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Build it with the Architect" }));

    expect(useArchitectAskStore.getState().request?.text).toContain("Answer refund emails");
  });

  it("saves a profile update and keeps the session's account in step", async () => {
    state.suggestions = [suggestion("profile", { job_title: "Head of sales" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Save to my profile" }));

    await waitFor(() => expect(useAuthStore.getState().user?.job_title).toBe("Head of sales"));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("adds a role pack's routines in the background", async () => {
    state.suggestions = [suggestion("role_pack", { pack: "sales" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Add these routines" }));

    expect(state.accept).toHaveBeenCalledWith("s-role_pack");
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("declines for good, and says why when the answer is refused", async () => {
    state.suggestions = [suggestion("agent", { request: "r" })];
    state.dismiss.mockRejectedValue(new Error("gone"));
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(state.dismiss).toHaveBeenCalledWith("s-agent");
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it("saves a profile with nobody signed in without touching the session", async () => {
    useAuthStore.setState({ user: null });
    state.suggestions = [suggestion("profile", { job_title: "CFO" })];
    render(<SuggestionCards agentId="a-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Save to my profile" }));

    await waitFor(() => expect(state.accept).toHaveBeenCalled());
    expect(useAuthStore.getState().user).toBeNull();
  });
});
