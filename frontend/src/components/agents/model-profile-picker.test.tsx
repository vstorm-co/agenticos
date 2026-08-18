import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
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
  // The real form is a provider, a model id and a key from the vault, tested in
  // `add-model.integration.test.tsx` - including that it starts on the model in
  // use. What this panel owes it is the callback and that model, so the stand-in
  // prints which one it was handed.
  AddModel: ({
    onCreated,
    selected,
  }: {
    onCreated: (profile: { id: string }) => void;
    selected?: { label: string };
  }) => {
    // Read once, like the real form: its fields are `useState(selected?.…)`, so a
    // prop that arrives later moves nothing. That is the whole reason the panel
    // keys this component, and a stand-in that re-read the prop on every render
    // would pass with the key removed.
    const [seeded] = useState(selected?.label ?? "nothing");
    return (
      <>
        <button type="button" onClick={() => onCreated({ id: "p-new" })}>
          Add model
        </button>
        <span data-testid="form-starts-on">{seeded}</span>
      </>
    );
  },
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

  it("starts the form on the model the agent is on", () => {
    // The panel used to answer "which model" in a line above the form and ask it in
    // the form's two fields, which are the same question - so the fields said
    // "Choose a provider" over a line naming the provider. They start on it now.
    mount({ allowAdd: true, value: "p1" });

    expect(screen.getByTestId("form-starts-on")).toHaveTextContent("openai default");
  });

  it("names the model in use without repeating what the fields say", () => {
    // The line survives because it answers *which named profile* is in use, which
    // the two fields cannot - they carry the provider and the model id. What it no
    // longer carries is that pair, which is what made it read the model twice.
    const derived = profile({ label: "OpenRouter · openai/gpt-5.5", provider: "openrouter" });

    mount({ allowAdd: true, value: "p1", profiles: [derived] });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("OpenRouter · openai/gpt-5.5")).toBeInTheDocument();
    expect(within(current).queryByText(/openrouter · openai\/gpt-5\.5/)).toBeNull();
  });

  it("starts it on the model once the profiles arrive, not only when they were already there", () => {
    // `value` and `profiles` do not land together: an agent already pointed at a
    // model renders with the id while the list is still in flight, so keying the
    // form on the id meant the key never changed once the list came back and the
    // fields kept the nothing they mounted with. "Choose a provider" over an agent
    // that plainly has one - which passed on a warm laptop and failed in CI.
    const { rerender } = render(
      <ModelProfilePicker profiles={[]} value="p1" allowAdd onChange={vi.fn()} />,
      { wrapper },
    );
    expect(screen.getByTestId("form-starts-on")).toHaveTextContent("nothing");

    rerender(<ModelProfilePicker profiles={[profile()]} value="p1" allowAdd onChange={vi.fn()} />);

    expect(screen.getByTestId("form-starts-on")).toHaveTextContent("openai default");
  });

  it("starts it on nothing where the agent is on nothing", () => {
    mount({ allowAdd: true, value: null });

    expect(screen.getByTestId("form-starts-on")).toHaveTextContent("nothing");
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

  it("tells an empty organization what is wrong and where a model comes from", () => {
    mount({ profiles: [] });

    expect(screen.getByText(/no models yet/)).toBeInTheDocument();
    // The path out, rather than only the problem: it names where models come from —
    // the Builder, by a member who manages connections — without claiming this
    // reader lacks a permission, which a picker that only knows `allowAdd` cannot
    // tell (the delegation picker passes none yet its caller may hold it).
    expect(screen.getByText(/added in the Builder/)).toBeInTheDocument();
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
    mount({ allowAdd: true, allowRemove: true });

    await userEvent.click(screen.getByRole("button", { name: "Remove openai default" }));

    expect(deleteProfile.mutate).toHaveBeenCalledWith("p1");
  });

  it("offers a panel that only chooses no way to delete a model every agent may use", () => {
    mount();

    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });

  it("lets a panel create a model without letting it destroy one", async () => {
    // The reason the two are separate flags. The knowledge-base dialog has to be
    // able to define the model that reads its images and store the key for it,
    // or a fresh deployment cannot finish the form at all; deleting an
    // organization-wide profile that agents are pointed at is a bigger claim
    // than a collection form makes.
    const onChange = vi.fn();
    mount({ allowAdd: true, onChange });

    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(onChange).toHaveBeenCalledWith("p-new");
  });

  it("states which model is in use even where the panel only chooses", () => {
    // The line moved out of the add-capable branch: whether the chosen profile
    // has a key is what decides whether anything runs, and in a list of a dozen
    // saved models the chosen one's badge is a badge among twelve.
    mount({ value: "p1" });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("openai default")).toBeInTheDocument();
    expect(within(current).getByText("no key")).toBeInTheDocument();
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

  it("says the model in use has no key, which is what decides whether it runs", () => {
    mount({ allowAdd: true, value: "p1" });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("no key")).toBeInTheDocument();
  });

  it("says what the agent runs on once", () => {
    // A label is derived from the provider and the model unless somebody typed
    // their own, so appending `provider · model` after it read
    // `OpenRouter · openai/gpt-5.5 openrouter · openai/gpt-5.5` - on the strip the
    // choose-only panel still has, and on every row of the saved-model list.
    const derived = profile({ label: "OpenRouter · openai/gpt-5.5", provider: "openrouter" });

    mount({ value: "p1", profiles: [derived] });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("OpenRouter · openai/gpt-5.5")).toBeInTheDocument();
    expect(within(current).queryByText(/openrouter · openai\/gpt-5\.5/)).toBeNull();
  });

  it("still names the model where the label does not, on the row that offers it", () => {
    // The other half of `modelDetail`: a name somebody chose says nothing about what
    // runs. It is the *list* that carries it now - the line above the form carries
    // the name, and the form's own fields carry the pair.
    mount({ value: "p1", profiles: [profile({ label: "the cheap one" })] });

    expect(screen.getByText("openai · gpt-4.1")).toBeInTheDocument();
  });

  it("names what the agent runs on rather than relying on it reading differently", () => {
    // The strip and the selected row now hold the same string, which is what
    // saying it once costs. The caption is what tells them apart, and it is
    // visible rather than only an accessible name.
    mount({ value: "p1", profiles: [profile({ label: "OpenRouter · openai/gpt-5.5" })] });

    const current = screen.getByRole("group", { name: "Current model" });
    expect(within(current).getByText("Current model")).toBeInTheDocument();
  });
});
