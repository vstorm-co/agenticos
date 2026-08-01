import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModelProfilePicker } from "./model-profile-picker";
import type { ModelProfile } from "@/types/providers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { ...actual.apiClient, get: vi.fn().mockResolvedValue({ items: [], total: 0 }) },
  };
});

const deleteProfile = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("@/hooks", () => ({ useModelProviders: () => ({ deleteProfile }) }));

// The real form is a provider, a model id and a key from the vault, tested in
// `add-model.integration.test.tsx`. What this panel owes it is the callback: a
// model created here is also the model the agent moves onto.
vi.mock("@/components/agents/add-model", () => ({
  AddModel: ({ onCreated }: { onCreated: (profile: { id: string }) => void }) => (
    <button type="button" onClick={() => onCreated({ id: "p-new" })}>
      Add model
    </button>
  ),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

function profile(overrides: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "p1",
    label: "openai default",
    provider: "openai",
    model: "gpt-4.1",
    secret_id: null,
    params: {},
    allow_byo: false,
    fallback_profile_ids: [],
    ...overrides,
  };
}

function mount(props: Partial<Parameters<typeof ModelProfilePicker>[0]> = {}) {
  render(<ModelProfilePicker profiles={[profile()]} value={null} onChange={vi.fn()} {...props} />, {
    wrapper,
  });
}

describe("ModelProfilePicker", () => {
  it("does not offer to add a model where it is only a choice", () => {
    // The regression this pins: the chat popover answers "which model should
    // this conversation run on". Adding one creates something every agent in
    // the organization can be pointed at - from a panel somebody opened to
    // change a single reply. It leaked in when the Builder gained the flow.
    mount();

    expect(screen.queryByRole("button", { name: "Add a model" })).toBeNull();
    expect(screen.queryByText(/rotate a key or repoint/)).toBeNull();
  });

  it("offers it where an agent is configured, without asking first", () => {
    // The form is the panel, not a state of it. Choosing a model is choosing a
    // provider, a model and a key; a list of profiles somebody else created is
    // not where that decision starts, and on a fresh deployment the list is
    // empty and the real control was a click away behind "Add a model".
    mount({ allowAdd: true });

    expect(screen.getByRole("button", { name: "Add model" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a model" })).toBeNull();
  });

  it("keeps the saved models one disclosure down rather than dropping them", () => {
    // A named profile is what lets an organization rotate a key or repoint every
    // agent at once, so it does not go away - it just stops being the first
    // thing anybody sees.
    mount({ allowAdd: true });

    expect(screen.getByText("Use a saved model (1)")).toBeInTheDocument();
  });

  it("states which model the agent is on above the form that would change it", () => {
    // The form being the default view puts the one fact somebody opens this
    // panel to check at risk of being the only thing behind a disclosure.
    mount({ allowAdd: true, value: "p1" });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("openai default")).toBeInTheDocument();
  });

  it("says a model has no key wherever it is shown", () => {
    // The one fact that decides whether the run can answer at all. Hiding it in
    // the chat would mean picking a model and finding out from a failed reply.
    mount();

    expect(screen.getByText("no key")).toBeInTheDocument();
  });

  it("names the model, not just the label somebody typed", () => {
    mount();

    expect(screen.getByText("openai · gpt-4.1")).toBeInTheDocument();
  });

  it("tells an empty organization what is wrong without offering the fix it cannot give", () => {
    mount({ profiles: [] });

    expect(screen.getByText(/no models yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a model" })).toBeNull();
  });

  it("moves the agent onto the model that was just created", async () => {
    // Selected, not merely added: somebody who came here to choose a model has
    // chosen one, and leaving the agent on the old value makes the work look
    // like it did not take.
    const onChange = vi.fn();
    mount({ allowAdd: true, onChange });

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(onChange).toHaveBeenCalledWith("p-new");
  });

  it("moves the agent onto a saved model that was picked", async () => {
    const onChange = vi.fn();
    mount({ onChange });

    await userEvent.click(screen.getByRole("radio", { name: "openai default" }));

    expect(onChange).toHaveBeenCalledWith("p1");
  });

  it("marks which saved model the agent is on", () => {
    mount({ value: "p1" });

    expect(screen.getByRole("radio", { name: "openai default" })).toBeChecked();
  });

  it("deletes a saved model only where models are managed", async () => {
    mount({ allowAdd: true });

    await userEvent.click(screen.getByRole("button", { name: "Remove openai default" }));

    expect(deleteProfile.mutate).toHaveBeenCalledWith("p1");
  });

  it("offers the chat no way to delete a model every agent may be pointed at", () => {
    mount();

    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });

  it("accepts nothing from somebody who cannot edit the spec", async () => {
    const onChange = vi.fn();
    mount({ onChange, disabled: true });

    await userEvent.click(screen.getByRole("radio", { name: "openai default" }));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("counts a model keyed from the vault as keyed", () => {
    // The vault secret is the only key a profile has. This once also tested a
    // `credential_id` the API had stopped sending, and `undefined === null` is
    // false - so the badge appeared on nothing, including the profiles that
    // really had no key. `models.spec.ts` is what caught that; a fixture
    // supplying the missing field is what hid it here.
    mount({ profiles: [profile({ secret_id: "s-1" })] });

    expect(screen.queryByText("no key")).toBeNull();
  });

  it("says the current model has no key, where the agent's own line is", () => {
    mount({ allowAdd: true, value: "p1" });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("no key")).toBeInTheDocument();
  });
});
