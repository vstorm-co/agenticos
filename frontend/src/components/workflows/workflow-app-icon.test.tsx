import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { catalogWorkflowApp, WORKFLOW_APPS } from "./apps";
import { WorkflowAppIcon } from "./workflow-app-icon";
import type { McpCatalogEntry } from "@/types/mcp";

vi.mock("@/components/icons/custom-icons", async () => {
  const actual = await vi.importActual<typeof import("@/components/icons/custom-icons")>(
    "@/components/icons/custom-icons",
  );
  return { ...actual, useCustomIcons: () => new Set(["acme"]) };
});
const server: McpCatalogEntry = {
  key: "airtable",
  name: "Airtable",
  description: "",
  category: "productivity",
  auth: "oauth",
  url: "https://mcp.airtable.com/mcp",
  docs_url: null,
  token_hint: null,
  icon: null,
};

describe("workflow service logos", () => {
  it("draws catalog logos even without a mapped brand or an account", () => {
    const app = catalogWorkflowApp(server);
    expect(app.url).toBe(server.url);
    const { container } = render(<WorkflowAppIcon app={app} name={server.name} />);
    expect(container.querySelector("img")?.getAttribute("src")).toMatch(/^data:image\//);
    expect(container.querySelector("svg.lucide-zap")).toBeNull();
  });
  it("uses deployment icons or distinct name monograms when there is no baked logo", () => {
    const { container, rerender } = render(
      <WorkflowAppIcon
        app={catalogWorkflowApp({ ...server, url: null, icon: "acme" })}
        name="Acme"
      />,
    );
    expect(container.querySelector<HTMLElement>("[style]")?.style.maskImage).toBe(
      'url("/api/catalog/icons/acme")',
    );
    rerender(
      <WorkflowAppIcon
        app={catalogWorkflowApp({ ...server, url: null, name: "Future CRM" })}
        name="Future CRM"
      />,
    );
    expect(container.textContent).not.toBe("");
    expect(container.querySelector("svg.lucide-zap")).toBeNull();
  });
  it("keeps a known app's own mark rather than its suite's catalog logo", () => {
    const gmail = WORKFLOW_APPS.find((app) => app.id === "gmail");
    if (!gmail) throw new Error("Gmail missing");
    const { container } = render(
      <WorkflowAppIcon app={{ ...gmail, url: server.url }} name="Gmail" />,
    );
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});
