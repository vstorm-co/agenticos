import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { useUnsavedChanges } from "./use-unsaved-changes";

type Props = Parameters<typeof useUnsavedChanges>[1];

const COPY = { key: "kept", base: 2 };
const kept = () => localStorage.getItem("kept");

function mount(initial: Props) {
  return renderHook((props: Props) => useUnsavedChanges("place", props), {
    initialProps: initial,
  });
}

beforeEach(() => useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false }));

describe("useUnsavedChanges", () => {
  it("is held only while there is a change, and kept in the browser meanwhile", () => {
    const discard = vi.fn();
    const { rerender } = mount({ dirty: false, discard, copy: { ...COPY, value: "a" } });
    expect(useUnsavedChangesStore.getState().sources).toEqual({});
    expect(kept()).toBeNull();

    rerender({ dirty: true, discard, copy: { ...COPY, value: "ab" } });
    expect(useUnsavedChangesStore.getState().sources.place).toBeDefined();
    expect(JSON.parse(kept()!)).toMatchObject({ base: 2, value: "ab" });

    // Undone here: nothing is held, and nothing is kept.
    rerender({ dirty: false, discard, copy: { ...COPY, value: "a" } });
    expect(useUnsavedChangesStore.getState().sources).toEqual({});
    expect(kept()).toBeNull();
  });

  it("keeps the copy when it goes away with the change still in it", () => {
    const { unmount } = mount({ dirty: true, discard: vi.fn(), copy: { ...COPY, value: 1 } });
    unmount();
    expect(kept()).not.toBeNull();
    expect(useUnsavedChangesStore.getState().sources).toEqual({});
  });

  it("forgets the copy once saved on the way out, and keeps it when the save is refused", async () => {
    const save = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    mount({ dirty: true, save, discard: vi.fn(), copy: { ...COPY, value: 1 } });
    const held = useUnsavedChangesStore.getState().sources.place!;
    await act(async () => expect(await held.save!()).toBe(false));
    expect(kept()).not.toBeNull();
    await act(async () => expect(await held.save!()).toBe(true));
    expect(kept()).toBeNull();
  });

  it("forgets the copy as it discards, and offers no save it was not given", () => {
    const discard = vi.fn();
    const { result } = mount({ dirty: true, discard, copy: { ...COPY, value: 1 } });
    const held = useUnsavedChangesStore.getState().sources.place!;
    expect(held.save).toBeUndefined();
    act(() => held.discard());
    expect(discard).toHaveBeenCalled();
    expect(kept()).toBeNull();
    // And a place without a copy has nothing to forget.
    expect(() => result.current.forget()).not.toThrow();
  });

  it("reads a save given late, and treats a save taken away as refused", async () => {
    const save = vi.fn().mockResolvedValue(true);
    const { rerender } = mount({ dirty: true, save, discard: vi.fn() });
    const held = useUnsavedChangesStore.getState().sources.place!;
    rerender({ dirty: true, save: undefined, discard: vi.fn() });
    expect(useUnsavedChangesStore.getState().sources.place?.save).toBeUndefined();
    await act(async () => expect(await held.save!()).toBe(false));
    expect(save).not.toHaveBeenCalled();
  });
});
