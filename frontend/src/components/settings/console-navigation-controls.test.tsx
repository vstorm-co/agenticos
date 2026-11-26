import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import {
  ConsoleNavigationControls,
  ConsoleNavigationSelection,
} from "./console-navigation-controls";

it("drafts a simple selection and saves only after an explicit click", async () => {
  const save = vi.fn<(value: string[] | null, onSaved: () => void) => void>();
  render(
    <ConsoleNavigationControls
      value={null}
      allowed={["chat", "inbox", "agents"]}
      simple={["chat", "inbox"]}
      disabled={false}
      onSave={save}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Simple assistant" }));
  expect(screen.getByRole("checkbox", { name: "Agents" })).not.toBeChecked();
  expect(save).not.toHaveBeenCalled();
  const proceed = vi.fn();
  act(() => useUnsavedChangesStore.getState().leave(proceed));
  expect(proceed).not.toHaveBeenCalled();
  await act(async () => {
    await useUnsavedChangesStore.getState().answer("discard");
  });
  expect(proceed).toHaveBeenCalledOnce();
  expect(screen.getByRole("checkbox", { name: "Agents" })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Simple assistant" }));

  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[0]?.[0]).toEqual(["chat", "inbox"]);
  act(() => save.mock.calls[0]?.[1]());
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});
it("supports an intentionally empty selection, discard and inheritance", async () => {
  const save = vi.fn();
  render(
    <ConsoleNavigationControls
      value={["chat"]}
      allowed={["chat"]}
      disabled={false}
      onSave={save}
    />,
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "Chat" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[0]?.[0]).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(screen.getByRole("checkbox", { name: "Chat" })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Use inherited navigation" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[1]?.[0]).toBeNull();
});
it("cannot widen the allowed list, and labels unavailable choices", async () => {
  const change = vi.fn();
  render(
    <ConsoleNavigationSelection value={[]} allowed={["chat"]} disabled={false} onChange={change} />,
  );
  expect(screen.getByRole("checkbox", { name: "Agents" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Chat" }));
  expect(change).toHaveBeenCalledWith(["chat"]);
});

it("shows only organization-offered destinations in personal settings", () => {
  render(
    <ConsoleNavigationSelection
      value={null}
      allowed={["chat"]}
      disabled={false}
      showUnavailable={false}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.queryByRole("checkbox", { name: "Agents" })).toBeNull();
});
it("does not allow editing while a navigation save is pending", () => {
  render(<ConsoleNavigationControls value={null} allowed={["chat"]} disabled onSave={vi.fn()} />);
  expect(screen.getByRole("checkbox", { name: "Chat" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Use inherited navigation" })).toBeDisabled();
});

it("keeps optional event sources available without selecting them in inherited navigation", async () => {
  const save = vi.fn();
  render(
    <ConsoleNavigationControls
      value={null}
      allowed={["chat", "eventSources"]}
      inherited={["chat"]}
      disabled={false}
      onSave={save}
    />,
  );
  expect(screen.getByRole("checkbox", { name: "Chat" })).toBeChecked();
  const optional = screen.getByRole("checkbox", { name: "Event sources" });
  expect(optional).not.toBeChecked();
  await userEvent.click(optional);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[0]?.[0]).toEqual(["chat", "eventSources"]);
  await userEvent.click(screen.getByRole("button", { name: "Use inherited navigation" }));
  expect(optional).not.toBeChecked();
});
