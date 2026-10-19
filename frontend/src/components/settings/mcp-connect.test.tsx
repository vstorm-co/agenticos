import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../messages/en.json";
import { McpConnect } from "./mcp-connect";

function renderCard() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <McpConnect />
    </NextIntlClientProvider>,
  );
}

describe("McpConnect", () => {
  it("shows the server URL and Claude Code's command, signing in through the browser", () => {
    renderCard();

    expect(screen.getByText("http://localhost:8000/mcp")).toBeInTheDocument();
    expect(screen.getByText(/^claude mcp add --transport http agenticos /)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Through the browser" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("link", { name: "What the MCP server can do" })).toHaveAttribute(
      "href",
      expect.stringContaining("/mcp/#agenticos-as-an-mcp-server"),
    );
  });

  it("switches every snippet to the API key", async () => {
    renderCard();

    await userEvent.click(screen.getByRole("radio", { name: "With an API key" }));
    expect(screen.getByRole("radio", { name: "With an API key" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByText(/--header "Authorization: Bearer \$AGENTICOS_API_KEY"/),
    ).toBeInTheDocument();
    expect(screen.getByText(/cannot open a browser/)).toBeInTheDocument();
  });

  it("marks every client's tab with its icon", () => {
    renderCard();

    for (const name of ["Claude Code", "Codex", "Claude Desktop", "Cursor", "VS Code"]) {
      expect(screen.getByRole("tab", { name }).querySelector("svg")).not.toBeNull();
    }
  });

  it("tells Claude Desktop to add a custom connector, with no command to copy", async () => {
    renderCard();

    await userEvent.click(screen.getByRole("tab", { name: "Claude Desktop" }));
    expect(screen.getByText(/Add custom connector/)).toBeInTheDocument();
    expect(screen.queryByText(/^claude mcp add/)).not.toBeInTheDocument();
  });

  it("gives Codex its add and login commands", async () => {
    renderCard();

    await userEvent.click(screen.getByRole("tab", { name: "Codex" }));
    expect(screen.getByText(/codex mcp login agenticos/)).toBeInTheDocument();
  });
});
