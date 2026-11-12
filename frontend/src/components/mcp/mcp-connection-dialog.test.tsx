import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { McpConnectionDialog } from "./mcp-connection-dialog";
import type { DraftState } from "./mcp-server-list-types";
import { probeMcpSignIn } from "@/lib/mcp-connections-api";
import { rowForEntry } from "@/lib/mcp-servers";
import type { McpCatalogEntry } from "@/types/mcp";

vi.mock("@/lib/mcp-connections-api", () => ({ probeMcpSignIn: vi.fn() }));
vi.mock("@/hooks", () => ({
  useGroups: () => ({ groups: [{ id: "g-fin", name: "Finance", icon: null }] }),
  useMembers: () => ({ members: [] }),
}));

beforeEach(() => vi.clearAllMocks());

const NOTION = { key: "notion", name: "Notion", auth: "oauth", url: "https://mcp.notion.com/mcp" };

function custom(): DraftState {
  return {
    scope: "personal",
    row: {
      key: "custom",
      name: "Custom",
      description: null,
      descriptionKey: null,
      category: "custom",
      auth: "token",
      url: null,
      docsUrl: null,
      tokenHint: null,
      entry: null,
      organizations: [],
      personals: [],
    },
    existing: null,
  } as unknown as DraftState;
}

function open(draft: DraftState, onSubmit = vi.fn()) {
  render(
    <McpConnectionDialog
      draft={draft}
      onClose={vi.fn()}
      submitting={false}
      canManageOrganization
      onSubmit={onSubmit}
    />,
  );
  return onSubmit;
}

async function typeAddress(url: string) {
  await userEvent.type(screen.getByLabelText("Server URL"), url);
  await userEvent.tab();
}

describe("OAuth setup guidance", () => {
  it("shows the catalog prerequisites for OAuth instead of hiding them with the token input", () => {
    const row = rowForEntry(NOTION as unknown as McpCatalogEntry);
    row.tokenHint = "Enable the Calendar MCP API and register a web OAuth client.";
    open({ scope: "personal", row, existing: null });

    expect(screen.getByText(row.tokenHint, { selector: "p.text-sm" })).toBeVisible();
    expect(screen.getByLabelText("Access token").parentElement).toHaveClass("hidden");
  });
});

describe("the account choice", () => {
  it("recommends each person's own account for a server people sign in to", () => {
    const entry = NOTION as unknown as McpCatalogEntry;
    open({ scope: "organization", row: rowForEntry(entry), existing: null });

    const own = screen.getByRole("radio", { name: /^My own account/ });
    expect(own).toHaveTextContent("Recommended");
    expect(screen.getByRole("radio", { name: /^One shared account/ })).not.toHaveTextContent(
      "Recommended",
    );
  });
});

describe("who an organization server is for (#2072)", () => {
  const github = () =>
    rowForEntry({
      key: "github",
      name: "GitHub",
      auth: "token",
      url: "https://api.githubcopilot.com/mcp/",
    } as unknown as McpCatalogEntry);

  it("limits a new shared account to chosen groups, with no only-me beside it", async () => {
    const onSubmit = open({ scope: "organization", row: github(), existing: null });

    expect(screen.queryByRole("radio", { name: /Only me/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Some people/ }));
    await userEvent.click(screen.getByRole("button", { name: "Finance" }));
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: "organization",
        audience: { visibility: "private", group_ids: ["g-fin"], user_ids: [] },
      }),
    );
  });

  it("asks nothing of a person's own account", async () => {
    open({ scope: "personal", row: github(), existing: null });

    expect(screen.queryByRole("radiogroup", { name: "Who can use it" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /^One shared account/ }));
    expect(screen.getByRole("radiogroup", { name: "Who can use it" })).toBeInTheDocument();
  });
});

describe("a server added by its address", () => {
  it("offers sign-in when the server supports it", async () => {
    vi.mocked(probeMcpSignIn).mockResolvedValue({ sign_in: true, registers_clients: true });
    const onSubmit = open(custom());

    await typeAddress("https://mcp.example.com/mcp");

    expect(await screen.findByText(/supports sign-in. Connect opens it/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "OAuth" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ auth: "oauth" }));
  });

  it("asks for a client made by hand when the server registers none", async () => {
    vi.mocked(probeMcpSignIn).mockResolvedValue({ sign_in: true, registers_clients: false });
    open(custom());

    await typeAddress("https://mcp.example.com/mcp");

    expect(await screen.findByText(/does not register apps itself/)).toBeInTheDocument();
  });

  it("says when there is no sign-in, and leaves the choice alone", async () => {
    vi.mocked(probeMcpSignIn).mockResolvedValue({ sign_in: false, registers_clients: false });
    open(custom());

    await typeAddress("https://mcp.example.com/mcp");

    expect(await screen.findByText(/No sign-in found/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "OAuth" })).toHaveAttribute("aria-checked", "false");
  });

  it("says nothing when the check could not run, or for no address", async () => {
    vi.mocked(probeMcpSignIn).mockRejectedValue(new Error("refused"));
    open(custom());

    await userEvent.click(screen.getByLabelText("Server URL"));
    await userEvent.tab();
    expect(probeMcpSignIn).not.toHaveBeenCalled();

    await typeAddress("https://mcp.example.com/mcp");
    await waitFor(() => expect(probeMcpSignIn).toHaveBeenCalled());
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("the server's own instructions", () => {
  function editing(includeInstructions: boolean): DraftState {
    return {
      ...custom(),
      existing: {
        id: "c1",
        name: "notion",
        url: "https://mcp.notion.com/mcp",
        label: null,
        has_auth_token: false,
        include_instructions: includeInstructions,
      },
    } as unknown as DraftState;
  }

  it("keeps an unchanged existing prefix when saving another setting", async () => {
    const draft = editing(false);
    if (!draft.existing) throw new Error("Missing connection fixture");
    draft.existing.name = "notion--work-";
    const onSubmit = open(draft);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ name: "notion--work-" }));
  });

  it("is offered only on a connection that exists, off unless it was opted in", async () => {
    const onSubmit = open(editing(false));

    const toggle = screen.getByRole("switch", { name: /server's own instructions/ });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ includeInstructions: true }));
  });

  it("is not offered while connecting a new server", () => {
    open(custom());

    expect(screen.queryByRole("switch", { name: /server's own instructions/ })).toBeNull();
  });
});

describe("a second account on one service", () => {
  it("asks for its name up front and will not submit without one", async () => {
    const onSubmit = open({ ...custom(), needsLabel: true } as DraftState);

    expect(screen.getByText(/already have an account on this service/)).toBeInTheDocument();
    await typeAddress("https://mcp.example.com/mcp");
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("aria-invalid", "true");

    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Work");
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ label: "Work" }));
  });
});

describe("human-entered prefixes", () => {
  it("formats a pasted prefix on blur and sends its canonical value", async () => {
    const onSubmit = open(custom());
    await userEvent.type(screen.getByLabelText("Name", { exact: true }), "Company CRM");
    const prefix = screen.getByLabelText("Tool prefix");
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "Support CRM");
    expect(prefix).toHaveValue("Support CRM");
    await userEvent.tab();
    expect(prefix).toHaveValue("support-crm");
    await typeAddress("https://mcp.example.test/mcp");
    await userEvent.click(screen.getByRole("button", { name: /Connect/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ name: "support-crm" }));
  });
});

describe("pending connection writes", () => {
  it("freezes the form and dismissal until the request settles", async () => {
    const draft = custom();
    const onClose = vi.fn();
    const onSubmit = vi.fn();
    const props = { draft, onClose, onSubmit, canManageOrganization: true };
    const view = render(<McpConnectionDialog {...props} submitting={false} />);
    await userEvent.type(screen.getByLabelText("Name", { exact: true }), "Company workspace");
    view.rerender(<McpConnectionDialog {...props} submitting />);
    expect(screen.getByLabelText("Name", { exact: true })).toBeDisabled();
    expect(screen.getByLabelText("Tool prefix")).toBeDisabled();
    expect(screen.getByLabelText("Server URL")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    view.rerender(<McpConnectionDialog {...props} submitting={false} />);
    expect(screen.getByLabelText("Name", { exact: true })).toBeEnabled();
    expect(screen.getByLabelText("Name", { exact: true })).toHaveValue("Company workspace");
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
  });
});
