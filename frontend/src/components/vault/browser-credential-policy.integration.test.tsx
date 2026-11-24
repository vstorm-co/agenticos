import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserCredentialPolicy } from "./browser-credential-policy";
import { BrowserCredentialMetadata } from "./browser-credential-metadata";
import { BrowserCredentialsField } from "@/components/agents/browser-credentials-field";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import type { BrowserCredentialPolicy as Policy } from "@/types/browser-credentials";
import type { Secret } from "@/types/secrets";
import type { ReactElement } from "react";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));
const owner = { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
const secret: Secret = {
  id: ids.secret,
  name: "Demo browser login",
  description: null,
  kind: "browser_login",
  hint: "never-visible",
  owner_user_id: ids.owner,
  can_edit: true,
  visibility: "private",
  browser: {
    allowed_origins: ["https://accounts.example"],
    available_fields: ["username", "password"],
    has_totp: false,
  },
};
let policy: Policy;
let client: QueryClient;
const agent = { id: "agent-a", name: "Draft assistant", status: "draft", can_run: true };
const teammate = { user_id: "member-a", full_name: "Sam", email: "sam@example.test" };
function setup(ui: ReactElement) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: owner });
  useOrgStore.setState({ activeOrgId: ids.org });
  policy = {
    secret_id: ids.secret,
    authorization_generation: ids.generation,
    mode: "personal",
    agent_ids: [],
    member_ids: [],
  };
  vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
    if (path.endsWith("/browser-policy")) return policy;
    if (path === "/agents")
      return options?.params && !Array.isArray(options.params) && options.params.skip !== "0"
        ? {
            items: [{ ...agent, id: "agent-b", name: "Second assistant", status: "published" }],
            total: 2,
          }
        : { items: [agent], total: 2 };
    if (path.includes("/members")) return { items: [teammate], total: 1 };
    return { items: [secret], total: 1 };
  });
  vi.mocked(apiClient.put).mockImplementation(async (_path, body) => {
    const next = body as { mode: Policy["mode"]; agent_ids: string[]; member_ids: string[] };
    policy = {
      ...policy,
      ...next,
      authorization_generation: "99999999-9999-4999-8999-999999999999",
    };
    return policy;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});
async function shared() {
  await userEvent.click(
    await screen.findByRole("combobox", { name: "Who may use this credential" }),
  );
  await userEvent.click(screen.getByRole("option", { name: "Named agents and teammates" }));
}
const save = () => screen.getByRole("button", { name: "Save browser use" });

describe("owner browser use", () => {
  it("retries an unavailable agent directory and supports removing a single named grant", async () => {
    let attempts = 0;
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path.endsWith("/browser-policy")) return policy;
      if (path === "/agents") {
        if (attempts++ === 0) throw new Error("Agents unavailable");
        return { items: [agent], total: 1 };
      }
      return { items: [teammate], total: 1 };
    });
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    await userEvent.click(await screen.findByRole("button", { name: "Check again" }));
    const choice = await screen.findByRole("checkbox", { name: "Draft assistant" });
    await userEvent.click(choice);
    await userEvent.click(choice);
    expect(choice).not.toBeChecked();
    expect(save()).toBeDisabled();
  });

  it("loads later teammates and preserves a selected member while additional pages arrive", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.endsWith("/browser-policy")) return policy;
      if (path === "/agents") return { items: [agent], total: 1 };
      const skip = options?.params && !Array.isArray(options.params) ? options.params.skip : "0";
      return skip === "0"
        ? { items: [teammate], total: 2 }
        : {
            items: [{ user_id: "member-b", full_name: null, email: "lee@example.test" }],
            total: 2,
          };
    });
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    const sam = await screen.findByRole("checkbox", { name: "Sam" });
    await userEvent.click(sam);
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("checkbox", { name: "lee@example.test" })).toBeVisible();
    expect(sam).toBeChecked();
  });

  it("enforces both audience limits without preventing revocation", async () => {
    policy = {
      ...policy,
      mode: "shared",
      agent_ids: Array.from({ length: 50 }, (_, i) => `selected-agent-${i}`),
      member_ids: Array.from({ length: 100 }, (_, i) => `selected-member-${i}`),
    };
    setup(<BrowserCredentialPolicy secret={secret} />);
    expect(await screen.findByRole("checkbox", { name: "Draft assistant" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Sam" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /selected-agent-0\)/ }));
    expect(screen.getByRole("checkbox", { name: "Draft assistant" })).not.toBeDisabled();
  });

  it("does not cache a policy result after the responding account changes", async () => {
    vi.mocked(apiClient.put).mockImplementation(() => {
      const response = Promise.resolve({ ...policy, authorization_generation: ids.child });
      void response.then(() =>
        queueMicrotask(() => useAuthStore.setState({ user: { ...owner, id: "new-owner" } })),
      );
      return response;
    });
    setup(<BrowserCredentialPolicy secret={secret} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save browser use" }));
    expect(
      await screen.findByText("Only the credential owner can change browser use."),
    ).toBeVisible();
    expect(
      client.getQueryData(["browser-credentials", "new-owner", ids.org, "policy", ids.secret]),
    ).toBeUndefined();
    expect(
      client.getQueryData<Policy>(["browser-credentials", ids.owner, ids.org, "policy", ids.secret])
        ?.authorization_generation,
    ).not.toBe(ids.child);
  });

  it("ignores an old pending policy write after the organization changes", async () => {
    let finish!: () => void;
    vi.mocked(apiClient.put).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = () => resolve(policy);
        }),
    );
    setup(<BrowserCredentialPolicy secret={secret} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save browser use" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledOnce());
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(403, "Unavailable in this organization"),
    );
    await act(async () => {
      useOrgStore.setState({ activeOrgId: "org-b" });
      finish();
    });
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText("Browser use saved.")).not.toBeInTheDocument();
  });

  it("requires the immutable owner and current edit access, not the creator", () => {
    setup(
      <BrowserCredentialPolicy
        secret={{ ...secret, owner_user_id: "someone-else", created_by_user_id: ids.owner }}
      />,
    );
    expect(screen.getByText("Only the credential owner can change browser use.")).toBeVisible();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("requires both named audiences and allows a runnable draft before its first publication", async () => {
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    expect(save()).toBeDisabled();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Draft assistant" }));
    expect(save()).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Sam" }));
    await userEvent.click(save());
    expect(apiClient.put).toHaveBeenCalledWith(
      `/secrets/${ids.secret}/browser-policy`,
      {
        generation: ids.generation,
        mode: "shared",
        agent_ids: ["agent-a"],
        member_ids: ["member-a"],
      },
      expect.objectContaining({ retryAfterRefresh: false }),
    );
    expect(await screen.findByText("Browser use saved.")).toBeVisible();
  });

  it("preserves unloaded selections and personal mode explicitly removes both grant sets", async () => {
    policy = {
      ...policy,
      mode: "shared",
      agent_ids: ["unloaded-agent"],
      member_ids: ["unavailable-member"],
    };
    setup(<BrowserCredentialPolicy secret={secret} />);
    expect(await screen.findByRole("checkbox", { name: /unloaded-agent/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /unavailable-member/ })).toBeChecked();
    await userEvent.click(screen.getByRole("combobox", { name: "Who may use this credential" }));
    await userEvent.click(screen.getByRole("option", { name: "Only me" }));
    await userEvent.click(save());
    expect(apiClient.put).toHaveBeenCalledWith(
      expect.any(String),
      { generation: ids.generation, mode: "personal", agent_ids: [], member_ids: [] },
      expect.any(Object),
    );
  });

  it("loads subsequent agent pages without dropping existing selections", async () => {
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Draft assistant" }));
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("checkbox", { name: "Second assistant" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Draft assistant" })).toBeChecked();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/agents",
      expect.objectContaining({ params: { skip: "1", limit: "100" } }),
    );
  });

  it("excludes archived and non-runnable choices and reports failed reads as unavailable", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path.endsWith("/browser-policy")) return policy;
      if (path === "/agents")
        return {
          items: [
            { ...agent, status: "archived", name: "Archived" },
            { ...agent, id: "blocked", can_run: false, name: "Blocked" },
          ],
          total: 2,
        };
      throw new Error("members unavailable");
    });
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    expect(
      await screen.findByText(
        "These choices could not be loaded. Check again before saving shared use.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: "Archived" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Blocked" })).not.toBeInTheDocument();
    expect(save()).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(4));
  });

  it("refuses a policy for a different secret", async () => {
    policy.secret_id = "another-secret";
    setup(<BrowserCredentialPolicy secret={secret} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByRole("button", { name: "Save browser use" })).not.toBeInTheDocument();
  });

  it("re-reads a generation refusal and discards the old policy draft", async () => {
    vi.mocked(apiClient.put).mockImplementation(async () => {
      policy = { ...policy, authorization_generation: "99999999-9999-4999-8999-999999999999" };
      throw new ApiError(409, "Browser use changed");
    });
    setup(<BrowserCredentialPolicy secret={secret} />);
    await shared();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Draft assistant" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Sam" }));
    await userEvent.click(save());
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Who may use this credential" }),
      ).toHaveTextContent("Only me"),
    );
    expect(screen.queryByRole("checkbox", { name: "Draft assistant" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeVisible();
  });

  it("hides a failed current policy read and offers an explicit retry", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("unavailable"));
    setup(<BrowserCredentialPolicy secret={secret} />);
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save browser use" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("button", { name: "Save browser use" })).toBeVisible();
  });

  it("does not carry a policy into a new organization", async () => {
    setup(<BrowserCredentialPolicy secret={secret} />);
    await screen.findByRole("button", { name: "Save browser use" });
    vi.mocked(apiClient.get).mockImplementation(() => new Promise(() => undefined));
    await act(async () => useOrgStore.setState({ activeOrgId: "org-b" }));
    expect(screen.queryByRole("button", { name: "Save browser use" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading current browser use");
  });
});

describe("safe metadata and reference binding", () => {
  it("retries a failed credential read and pages past technical keys without losing the audience", async () => {
    let attempts = 0;
    vi.mocked(apiClient.get).mockImplementation(async (_path, options) => {
      if (attempts++ === 0) throw new Error("Unavailable");
      const skip = options?.params && !Array.isArray(options.params) ? options.params.skip : "0";
      return skip === "0"
        ? {
            items: [{ ...secret, id: "technical", name: "Technical key", kind: "api_key" }],
            total: 2,
          }
        : { items: [secret], total: 2 };
    });
    const change = vi.fn();
    setup(<BrowserCredentialsField value={undefined} onChange={change} idPrefix="paged" />);
    await userEvent.click(await screen.findByRole("button", { name: "Check again" }));
    expect(
      await screen.findByText(
        "No browser credentials in the loaded results. Load more to continue.",
      ),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Demo browser login" }));
    expect(change).toHaveBeenCalledWith([ids.secret]);
  });

  it("explains an exhausted empty credential list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    setup(<BrowserCredentialsField value={null} onChange={vi.fn()} idPrefix="empty" />);
    expect(
      await screen.findByText(
        "Save a browser login or contact profile in Vault to select it here.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("shows only field names, origins and TOTP presence", () => {
    setup(
      <BrowserCredentialMetadata
        metadata={{
          ...secret.browser!,
          available_fields: ["password", "raw-sensitive-extra"],
          has_totp: true,
        }}
      />,
    );
    expect(screen.getByText("https://accounts.example")).toBeVisible();
    expect(screen.getByText("Password")).toBeVisible();
    expect(screen.getByText("Includes a verification code")).toBeVisible();
    expect(screen.queryByText("raw-sensitive-extra")).not.toBeInTheDocument();
  });

  it("shows a metadata-unavailable state without inventing values", () => {
    setup(<BrowserCredentialMetadata />);
    expect(screen.getByText("Browser metadata is unavailable.")).toBeVisible();
  });

  it("binds only browser kinds and preserves unloaded IDs until explicitly removed", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [secret, { ...secret, id: "api-key", name: "Technical API key", kind: "api_key" }],
      total: 2,
    });
    const change = vi.fn();
    setup(
      <BrowserCredentialsField
        value={["unloaded", "unloaded", 12]}
        onChange={change}
        idPrefix="browser"
      />,
    );
    await userEvent.click(await screen.findByRole("checkbox", { name: "Demo browser login" }));
    expect(change).toHaveBeenLastCalledWith(["unloaded", ids.secret]);
    expect(screen.queryByRole("checkbox", { name: "Technical API key" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /unloaded/ }));
    expect(change).toHaveBeenLastCalledWith([]);
    expect(screen.queryByText("never-visible")).not.toBeInTheDocument();
  });

  it("caps references at fifty and lets an owner remove an existing reference", async () => {
    const selected = Array.from({ length: 50 }, (_, index) => `old-${index}`);
    const change = vi.fn();
    setup(<BrowserCredentialsField value={selected} onChange={change} idPrefix="limit" />);
    expect(await screen.findByRole("checkbox", { name: "Demo browser login" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /\(old-0\)/ }));
    expect(change).toHaveBeenCalledWith(selected.slice(1));
  });

  it("makes a disabled binding read-only", async () => {
    setup(<BrowserCredentialsField value={[]} onChange={vi.fn()} idPrefix="disabled" disabled />);
    expect(await screen.findByRole("checkbox", { name: "Demo browser login" })).toBeDisabled();
  });
});
