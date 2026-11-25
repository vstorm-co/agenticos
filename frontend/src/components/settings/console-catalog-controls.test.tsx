import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ConsoleCatalogControls } from "./console-catalog-controls";
import type { CatalogPolicy } from "@/lib/console-experience-api";

const env = vi.hoisted(() => ({
  mcp: {
    servers: [
      { key: "github", name: "GitHub", description: "Code" },
      { key: "slack", name: "Slack", description: "Messages" },
    ],
    total: 101,
    isLoading: false,
    isFetching: false,
    error: null as Error | null,
    refetch: vi.fn(),
  },
  skills: {
    industries: [
      {
        id: "software",
        skills: [
          { key: "software/review", name: "Review", description: "Code review" },
          { key: "software/write", name: "Write", description: "Writing" },
        ],
      },
    ],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  },
  mcpRead: vi.fn(),
  skillRead: vi.fn(),
}));
vi.mock("@/hooks/use-mcp-servers", () => ({
  MCP_PAGE_SIZE: 50,
  useMcpCatalogPage: (...args: unknown[]) => {
    env.mcpRead(...args);
    return env.mcp;
  },
}));
vi.mock("@/hooks/use-skill-gallery", () => ({
  useSkillGallery: (enabled: boolean) => {
    env.skillRead(enabled);
    return env.skills;
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
  env.mcp.isLoading = false;
  env.mcp.isFetching = false;
  env.mcp.error = null;
  env.skills.isLoading = false;
  env.skills.isError = false;
});
function mount(
  kind: "mcp_gallery" | "skill_gallery" = "mcp_gallery",
  value?: CatalogPolicy | null,
  disabled = false,
) {
  const onSave = vi.fn<(value: CatalogPolicy | null, onSaved: () => void) => void>();
  const onDirtyChange = vi.fn<(dirty: boolean) => void>();
  const view = render(
    <ConsoleCatalogControls
      kind={kind}
      value={value}
      disabled={disabled}
      onSave={onSave}
      onDirtyChange={onDirtyChange}
    />,
  );
  return { onSave, onDirtyChange, ...view };
}
it("does not fetch choices until explicitly choosing an allow-list and saves an intentional empty list", async () => {
  const view = mount();
  expect(env.mcpRead).toHaveBeenLastCalledWith("", "", "", 0, false);
  expect(env.skillRead).toHaveBeenLastCalledWith(false);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await userEvent.click(screen.getByRole("combobox", { name: "MCP gallery" }));
  await userEvent.click(screen.getByRole("option", { name: "Choose entries" }));
  expect(env.mcpRead).toHaveBeenLastCalledWith("", "", "", 0, true);
  expect(screen.getByText("An empty selection offers no gallery entries.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(view.onSave).toHaveBeenCalledWith({ mode: "allow-list", keys: [] }, expect.any(Function));
  view.onSave.mock.calls[0]![1]();
});
it("keeps selected keys across pages and searches, and supports removal and discard", async () => {
  const view = mount("mcp_gallery", { mode: "allow-list", keys: ["retired"] });
  await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(env.mcpRead).toHaveBeenLastCalledWith("", "", "", 1, true);
  await userEvent.click(screen.getByRole("button", { name: "Previous" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Search" }), "git");
  expect(env.mcpRead).toHaveBeenLastCalledWith("git", "", "", 0, true);
  await userEvent.click(screen.getByRole("button", { name: "Remove retired" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(view.onSave).toHaveBeenCalledWith(
    { mode: "allow-list", keys: ["github"] },
    expect.any(Function),
  );
  await userEvent.click(screen.getByRole("button", { name: "Remove GitHub" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(screen.getByRole("button", { name: "Remove retired" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
it.each(["all", "available", "inherit"] as const)("saves %s distinctly", async (mode) => {
  const view = mount("mcp_gallery", { mode: "allow-list", keys: [] });
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(
    screen.getByRole("option", {
      name:
        mode === "all"
          ? "All available entries"
          : mode === "available"
            ? "Only organization-connected servers"
            : "Use inherited catalog",
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(view.onSave).toHaveBeenCalledWith(
    mode === "inherit" ? null : { mode, keys: [] },
    expect.any(Function),
  );
});
it("filters the skills shelf locally without paging MCP or starting an installation", async () => {
  mount("skill_gallery", { mode: "allow-list", keys: [] });
  expect(env.skillRead).toHaveBeenLastCalledWith(true);
  expect(env.mcpRead).toHaveBeenLastCalledWith("", "", "", 0, false);
  await userEvent.type(screen.getByRole("textbox", { name: "Search" }), "review");
  expect(screen.getByRole("checkbox", { name: "Review" })).toBeVisible();
  expect(screen.queryByRole("checkbox", { name: "Write" })).toBeNull();
  await userEvent.clear(screen.getByRole("textbox", { name: "Search" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Write" }));
  expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
});
it.each(["mcp_gallery", "skill_gallery"] as const)(
  "reports loading and retry for %s",
  async (kind) => {
    env.mcp.isLoading = true;
    env.skills.isLoading = true;
    const view = mount(kind, { mode: "allow-list", keys: [] });
    expect(screen.queryByRole("checkbox")).toBeNull();
    env.mcp.isLoading = false;
    env.skills.isLoading = false;
    env.mcp.error = new Error("offline");
    env.skills.isError = true;
    view.rerender(
      <ConsoleCatalogControls
        kind={kind}
        value={{ mode: "allow-list", keys: [] }}
        disabled={false}
        onSave={view.onSave}
      />,
    );
    expect(screen.getByRole("alert")).toBeVisible();
    await userEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Retry" }));
    expect(kind === "mcp_gallery" ? env.mcp.refetch : env.skills.refetch).toHaveBeenCalledOnce();
  },
);
it("bounds the selected keys and leaves an unavailable saved key removable", async () => {
  const view = mount("mcp_gallery", {
    mode: "allow-list",
    keys: Array.from({ length: 512 }, (_, i) => `saved-${i}`),
  });
  expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Remove saved-0" }));
  expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeEnabled();
  view.unmount();
  mount("mcp_gallery", { mode: "allow-list", keys: ["github"] }, true);
  expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeDisabled();
  expect(screen.getByRole("combobox")).toBeDisabled();
});
it("shows an empty result and respects in-flight pagination", () => {
  env.mcp.servers = [];
  env.mcp.isFetching = true;
  const view = mount("mcp_gallery", { mode: "allow-list", keys: [] });
  expect(screen.getByText("No matching entries")).toBeVisible();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  view.unmount();
  env.mcp.servers = [
    { key: "github", name: "GitHub", description: "Code" },
    { key: "slack", name: "Slack", description: "Messages" },
  ];
});

it("discards a catalog draft through the navigation guard before leaving", async () => {
  const { useUnsavedChangesStore } = await import("@/stores/unsaved-changes-store");
  mount("mcp_gallery", { mode: "allow-list", keys: [] });
  await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(proceed).toHaveBeenCalledOnce();
  expect(screen.getByRole("checkbox", { name: "GitHub" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
