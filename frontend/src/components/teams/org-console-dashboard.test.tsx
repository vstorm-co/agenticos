import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OrganizationConsoleDashboard } from "./org-console-dashboard";
import { widgetCatalog, type StoredEntry } from "@/lib/dashboard/preference";

const env = vi.hoisted(() => ({
  storedEntries: null as StoredEntry[] | null,
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-dashboard-layout", () => ({ useDashboardLayout: () => env }));
beforeEach(() => {
  env.storedEntries = null;
  env.isLoading = false;
  env.error = null;
  env.refetch.mockClear();
});
const catalog = widgetCatalog(() => true, false);
function mount(value?: { entries: StoredEntry[] } | null, disabled = false) {
  const save = vi.fn<(value: { entries: StoredEntry[] } | null, onSaved: () => void) => void>();
  const dirty = vi.fn<(value: boolean) => void>();
  const view = render(
    <OrganizationConsoleDashboard
      value={value}
      catalog={catalog}
      disabled={disabled}
      onSave={save}
      onDirtyChange={dirty}
    />,
  );
  return { save, dirty, ...view };
}
it("requires a saved personal arrangement and a separate explicit save before sharing", async () => {
  const view = mount();
  expect(screen.getByText("No role default: the standard home is used.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy my saved arrangement" })).toBeDisabled();
  expect(screen.getByRole("link", { name: "Arrange and save my dashboard" })).toHaveAttribute(
    "href",
    "/dashboard?view=org",
  );
  view.unmount();
  env.storedEntries = [
    { widget: "projects", span: "s6" },
    { kind: "section", label: "My work" },
  ];
  const ready = mount();
  await userEvent.click(screen.getByRole("button", { name: "Copy my saved arrangement" }));
  expect(ready.save).not.toHaveBeenCalled();
  expect(screen.getByText("My work")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(ready.save.mock.calls[0]![0]?.entries).toHaveLength(2);
  act(() => ready.save.mock.calls[0]![1]());
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
it("preserves an empty role default separately from inheriting the standard home", async () => {
  env.storedEntries = [];
  const view = mount({ entries: [{ widget: "projects", span: "s6" }] });
  await userEvent.click(screen.getByRole("button", { name: "Copy my saved arrangement" }));
  expect(screen.getByText("This role default intentionally has no cards.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(view.save).toHaveBeenCalledWith({ entries: [] }, expect.any(Function));
  await userEvent.click(screen.getByRole("button", { name: "Use standard dashboard" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(view.save).toHaveBeenLastCalledWith(null, expect.any(Function));
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
it.each(["agent_id", "user_id"] as const)(
  "cannot publish personal %s filters in a role default",
  (field) => {
    env.storedEntries = [{ widget: "runs", span: "s6", options: { [field]: "private-reference" } }];
    mount();
    expect(screen.getByRole("button", { name: "Copy my saved arrangement" })).toBeDisabled();
    expect(screen.getByText(/Remove person and agent filters/)).toBeVisible();
  },
);
it("keeps load failures distinct from having no saved layout", async () => {
  env.isLoading = true;
  const view = mount();
  expect(screen.queryByRole("button", { name: "Copy my saved arrangement" })).toBeNull();
  env.isLoading = false;
  env.error = new Error("offline");
  view.rerender(
    <OrganizationConsoleDashboard
      value={null}
      catalog={catalog}
      disabled={false}
      onSave={view.save}
      onDirtyChange={view.dirty}
    />,
  );
  expect(screen.getByRole("alert")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.refetch).toHaveBeenCalledOnce();
});
it("only previews widgets offered to this role and respects disabled controls", () => {
  const { unmount } = render(
    <OrganizationConsoleDashboard
      value={{
        entries: [
          { widget: "projects", span: "s6" },
          { widget: "spend", span: "s6" },
        ],
      }}
      catalog={[]}
      disabled
      onSave={vi.fn()}
      onDirtyChange={vi.fn()}
    />,
  );
  expect(screen.queryByText("Projects")).toBeNull();
  expect(screen.getByRole("button", { name: "Use standard dashboard" })).toBeDisabled();
  unmount();
  env.storedEntries = [];
  mount({ entries: [] }, true);
  expect(screen.getByRole("button", { name: "Copy my saved arrangement" })).toBeDisabled();
});

it("discards a copied role layout through the navigation guard", async () => {
  const { useUnsavedChangesStore } = await import("@/stores/unsaved-changes-store");
  env.storedEntries = [];
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Copy my saved arrangement" }));
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(proceed).toHaveBeenCalledOnce();
  expect(screen.getByText("No role default: the standard home is used.")).toBeVisible();
});
