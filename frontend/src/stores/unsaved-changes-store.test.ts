import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { useUnsavedChangesStore, type UnsavedSource } from "./unsaved-changes-store";

const store = () => useUnsavedChangesStore.getState();

function source(saved?: boolean): UnsavedSource & {
  discard: Mock<() => void>;
  save?: Mock<() => Promise<boolean>>;
} {
  const discard = vi.fn<() => void>();
  if (saved === undefined) return { discard };
  return { discard, save: vi.fn<() => Promise<boolean>>().mockResolvedValue(saved) };
}

beforeEach(() => useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false }));

describe("the unsaved changes store", () => {
  it("lets a way out through at once when nothing would be lost", () => {
    const proceed = vi.fn();
    store().register("other", source());
    store().leave(proceed, ["editor"]);
    expect(proceed).toHaveBeenCalled();
    expect(store().prompt).toBeNull();
  });

  it("holds a way out over what it would drop, and staying keeps everything", async () => {
    const editor = source(true);
    const proceed = vi.fn();
    store().register("editor", editor);
    store().register("grading", source(true));
    store().leave(proceed, ["editor", "gone"]);
    expect(store().prompt?.ids).toEqual(["editor"]);

    await store().answer("stay");
    expect(store().prompt).toBeNull();
    expect(proceed).not.toHaveBeenCalled();
    expect(editor.discard).not.toHaveBeenCalled();
  });

  it("discards every held change and goes on", async () => {
    const a = source();
    const b = source();
    const proceed = vi.fn();
    store().register("a", a);
    store().register("b", b);
    store().leave(proceed);
    await store().answer("discard");
    expect(a.discard).toHaveBeenCalled();
    expect(b.discard).toHaveBeenCalled();
    expect(proceed).toHaveBeenCalled();
  });

  it("goes on once everything saved, and stays at the first refusal", async () => {
    const proceed = vi.fn();
    const first = source(true);
    const refused = source(false);
    const later = source(true);
    store().register("first", first);
    store().register("refused", refused);
    store().register("later", later);
    store().leave(proceed);
    await store().answer("save");
    expect(first.save).toHaveBeenCalled();
    expect(later.save).not.toHaveBeenCalled();
    expect(proceed).not.toHaveBeenCalled();
    expect(store()).toMatchObject({ prompt: null, saving: false });

    store().unregister("refused");
    store().leave(proceed);
    await store().answer("save");
    expect(proceed).toHaveBeenCalled();
  });

  it("does not count a change that cannot be saved as saved", async () => {
    const proceed = vi.fn();
    store().register("unsavable", source());
    store().leave(proceed);
    await store().answer("save");
    expect(proceed).not.toHaveBeenCalled();
  });

  it("goes on when what it asked about went away before the answer", async () => {
    const proceed = vi.fn();
    store().register("editor", source());
    store().leave(proceed);
    store().unregister("editor");
    await store().answer("discard");
    expect(proceed).toHaveBeenCalled();
  });

  it("ignores an answer to a question nobody asked", async () => {
    await store().answer("discard");
    expect(store().prompt).toBeNull();
  });
});
