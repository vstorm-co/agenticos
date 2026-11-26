import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ExportResourceList } from "./export-resource-list";
import type { BundlePreview, BundleResource } from "@/lib/portability-api";

vi.mock("@/components/vault/provider-icon", () => ({
  ProviderIcon: ({ provider }: { provider: string }) => <span data-provider-icon={provider} />,
}));
const resource = (
  kind: string,
  name: string,
  definition: Record<string, unknown> | null = null,
): BundleResource => ({
  key: `${kind}/${name}`,
  kind,
  name,
  source_id: null,
  source_parent_id: null,
  source_version: null,
  definition,
  references: [],
  included: definition ? ["definition"] : [],
});
const rootResource = resource("agent", "Researcher", { description: "Root assistant" });
const rows = [
  rootResource,
  resource("agent_version", "Delegated research", { name: "Delegated research" }),
  resource("workflow", "Weekly review", { name: "Weekly review" }),
  resource("skill", "evidence-check", { description: "Verify source citations" }),
  resource("context", "Policy", { content: "Policy text" }),
  resource("knowledge_base", "Research docs", { name: "Research docs" }),
  resource("model_profile", "OpenRouter default", {
    provider: "openrouter",
    model: "anthropic/claude-haiku-5.5",
  }),
  resource("secret", "Provider key"),
  resource("table", "Observations", { name: "Observations" }),
];
function data(resources = rows): BundlePreview {
  return {
    bundle: {
      format: "agenticos.bundle",
      format_version: 1,
      roots: [rootResource.key],
      resources,
      assets: [],
    },
    options: [],
  };
}
it("groups dependencies, keeps the required root and shows genuine avatar/provider metadata", async () => {
  const include = vi.fn();
  const { container } = render(
    <ExportResourceList
      data={data()}
      format="yaml"
      busy={false}
      excluded={new Set()}
      layersByKey={{}}
      rootIdentity={{ agentId: "root", slug: "stable-research", hasAvatar: false }}
      onInclude={include}
      onLayers={vi.fn()}
    />,
  );
  expect(screen.getByRole("checkbox", { name: /Researcher/ })).toBeDisabled();
  for (const name of [
    "Required definition",
    "Agents",
    "Workflows",
    "Skills",
    "Context",
    "Knowledge bases",
    "Models & connections",
    "Other resources",
  ]) {
    expect(screen.getByRole("region", { name })).toBeVisible();
  }
  expect(container.querySelector('[data-agent-avatar="root"]')).toBeInTheDocument();
  expect(container.querySelector('[data-provider-icon="openrouter"]')).toBeInTheDocument();
  expect(screen.getByText("anthropic/claude-haiku-5.5")).toBeVisible();
  expect(screen.getByText("Verify source citations")).toBeVisible();
  expect(screen.getByText("Provider key")).toBeVisible();
  await userEvent.click(screen.getByRole("checkbox", { name: /evidence-check/ }));
  expect(include).toHaveBeenCalledWith("skill/evidence-check", false);
});
it("searches names and descriptions without changing hidden dependency selections", async () => {
  const include = vi.fn();
  render(
    <ExportResourceList
      data={data()}
      format="zip"
      busy={false}
      excluded={new Set()}
      layersByKey={{}}
      onInclude={include}
      onLayers={vi.fn()}
    />,
  );
  const search = screen.getByPlaceholderText("Search included resources");
  await userEvent.type(search, "citations");
  expect(screen.getByText("evidence-check")).toBeVisible();
  expect(screen.queryByText("Policy")).not.toBeInTheDocument();
  expect(include).not.toHaveBeenCalled();
  await userEvent.clear(search);
  expect(screen.getByRole("checkbox", { name: /Policy/ })).toBeChecked();
  await userEvent.type(search, "does not exist");
  expect(screen.getByText("No matching resources.")).toBeVisible();
});
it("keeps small exports compact and routes selectable binary layers through the same contract", async () => {
  const skill = resource("skill", "Writing", { description: "Write documents" });
  const preview = data([rootResource, skill]);
  preview.options = [
    {
      key: skill.key,
      available: true,
      can_create: true,
      reusable_id: null,
      layers: ["definition", "skill_files"],
    },
  ];
  const layers = vi.fn();
  const view = render(
    <ExportResourceList
      data={preview}
      format="zip"
      busy={false}
      excluded={new Set()}
      layersByKey={{}}
      onInclude={vi.fn()}
      onLayers={layers}
    />,
  );
  expect(screen.queryByPlaceholderText("Search included resources")).toBeNull();
  await userEvent.click(screen.getByRole("checkbox", { name: "Skill files" }));
  expect(layers).toHaveBeenCalledWith(skill.key, ["definition", "skill_files"]);
  view.rerender(
    <ExportResourceList
      data={preview}
      format="json"
      busy
      excluded={new Set([skill.key])}
      layersByKey={{}}
      onInclude={vi.fn()}
      onLayers={layers}
    />,
  );
  expect(screen.queryByRole("checkbox", { name: "Skill files" })).toBeNull();
  expect(screen.getByRole("checkbox", { name: /Writing/ })).toBeDisabled();
});
