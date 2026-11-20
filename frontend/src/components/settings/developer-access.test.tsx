import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { DeveloperAccess } from "./developer-access";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("./api-usage", () => ({ ApiUsage: () => <p>Usage</p> }));
vi.mock("./api-keys-manager", () => ({ ApiKeysManager: () => <p>Keys</p> }));
vi.mock("./mcp-connect", () => ({ McpConnect: () => <p>Connect a client</p> }));
vi.mock("./connected-apps", () => ({ ConnectedApps: () => <p>Connected clients</p> }));

afterEach(() => window.history.replaceState(null, "", "/"));

it("keeps legacy MCP entry points on MCP and records a switch to API in the URL", async () => {
  window.history.replaceState(null, "", "/settings/mcp");
  render(<DeveloperAccess initial="mcp" />);
  expect(screen.getByRole("tabpanel", { name: "MCP clients" })).toHaveTextContent(
    "Connected clients",
  );
  await userEvent.click(screen.getByRole("tab", { name: "API" }));
  expect(screen.getByRole("tabpanel", { name: "API" })).toHaveTextContent("Keys");
  expect(new URLSearchParams(window.location.search).get("access")).toBe("api");
  await userEvent.click(screen.getByRole("tab", { name: "MCP clients" }));
  expect(window.location.search).toBe("");
});

it("ignores an unknown inner view without hiding the requested access method", () => {
  window.history.replaceState(null, "", "/settings/mcp?access=unknown");
  render(<DeveloperAccess initial="mcp" />);
  expect(screen.getByRole("tab", { name: "MCP clients" })).toHaveAttribute("aria-selected", "true");
});
