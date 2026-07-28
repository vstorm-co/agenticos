import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ModelProfilePicker } from "./model-profile-picker";
import type { ModelProfile } from "@/types/providers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { ...actual.apiClient, get: vi.fn().mockResolvedValue({ items: [], total: 0 }) },
  };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function profile(overrides: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "p1",
    label: "openai default",
    provider: "openai",
    model: "gpt-4.1",
    credential_id: null,
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
    // the organization can be pointed at — from a panel somebody opened to
    // change a single reply. It leaked in when the Builder gained the flow.
    mount();

    expect(screen.queryByRole("button", { name: "Add a model" })).toBeNull();
    expect(screen.queryByText(/rotate a key or repoint/)).toBeNull();
  });

  it("offers it where an agent is configured", () => {
    mount({ allowAdd: true });

    expect(screen.getByRole("button", { name: "Add a model" })).toBeInTheDocument();
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
});
