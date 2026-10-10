import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { McpConnectionDialog } from "./mcp-connection-dialog";
import type { DraftState } from "./mcp-server-list-types";
import { probeMcpSignIn } from "@/lib/mcp-connections-api";
import { rowForEntry } from "@/lib/mcp-servers";
import type { McpCatalogEntry } from "@/types/mcp";

vi.mock("@/lib/mcp-connections-api", () => ({ probeMcpSignIn: vi.fn() }));

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
