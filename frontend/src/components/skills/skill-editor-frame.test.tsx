import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { SkillEditorFrame } from "./skill-editor-frame";

beforeEach(() => useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false }));

it("protects this skill's resource drafts while leaving unrelated editors untouched", async () => {
  const discard = vi.fn();
  const other = vi.fn();
  const onClose = vi.fn();
  useUnsavedChangesStore.getState().register("skill-resource:s1:file1", { discard });
  useUnsavedChangesStore.getState().register("skill-resource:s2:file2", { discard: other });
  render(
    <SkillEditorFrame id="s1" onClose={onClose}>
      <p>Instructions</p>
    </SkillEditorFrame>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).not.toHaveBeenCalled();
  await act(() => useUnsavedChangesStore.getState().answer("discard"));
  expect(discard).toHaveBeenCalledOnce();
  expect(other).not.toHaveBeenCalled();
  expect(onClose).toHaveBeenCalledOnce();
});
