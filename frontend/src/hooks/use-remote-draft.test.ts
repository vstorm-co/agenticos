import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRemoteDraft } from "./use-remote-draft";
import { announceChange } from "@/lib/live-updates";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import type { ChangeEvent } from "@/types/change-events";

type Draft = { instructions: string };

interface Props {
  local: Draft | null;
  stored: Draft | null | undefined;
  fetchedAt: number;
}

const ME = "me";
const adopt = vi.fn();

function change(overrides: Partial<ChangeEvent> = {}): ChangeEvent {
  return {
    organization_id: "org-1",
    resource: "agent",
    id: "agent-1",
    action: "updated",
    surface: "mcp",
    actor_user_id: "someone-else",
    actor_name: "Ada",
    ...overrides,
  };
}

const kept: Draft = { instructions: "Be kind." };
const theirs: Draft = { instructions: "Be brief." };
const mine: Draft = { instructions: "Be thorough." };

function mount(initial: Props) {
  return renderHook(
    (props: Props) => useRemoteDraft({ resource: "agent", id: "agent-1", adopt, ...props }),
    { initialProps: initial },
  );
}

beforeEach(() => {
  adopt.mockReset();
  useAuthStore.setState({ user: { id: ME } as User });
});

describe("useRemoteDraft", () => {
  it("holds saving from the event until the refetch, then adopts a clean draft silently", () => {
    const view = mount({ local: kept, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change()));
    expect(view.result.current.held).toBe(true);

    view.rerender({ local: kept, stored: theirs, fetchedAt: 2 });

    expect(adopt).toHaveBeenCalledWith(theirs);
    expect(view.result.current.held).toBe(false);
    expect(view.result.current.conflict).toBeNull();
  });

  it("asks before replacing edits made here, and keeps holding until it is answered", () => {
    const view = mount({ local: mine, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change()));
    view.rerender({ local: mine, stored: theirs, fetchedAt: 2 });

    expect(adopt).not.toHaveBeenCalled();
    expect(view.result.current.conflict?.actor_name).toBe("Ada");
    expect(view.result.current.held).toBe(true);

    act(() => view.result.current.reload());

    expect(adopt).toHaveBeenCalledWith(theirs);
    expect(view.result.current.held).toBe(false);
  });

  it("lets the editor keep their own version, which the next save stores over the other", () => {
    const view = mount({ local: mine, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change()));
    view.rerender({ local: mine, stored: theirs, fetchedAt: 2 });
    act(() => view.result.current.keepMine());

    expect(adopt).not.toHaveBeenCalled();
    expect(view.result.current.conflict).toBeNull();
    expect(view.result.current.held).toBe(false);
  });

  it("lets go without a word when the stored draft did not move", () => {
    const view = mount({ local: mine, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change()));
    view.rerender({ local: mine, stored: kept, fetchedAt: 2 });

    expect(view.result.current.held).toBe(false);
    expect(view.result.current.conflict).toBeNull();
    expect(adopt).not.toHaveBeenCalled();
  });

  it("does nothing while the refetch has not answered, nor when it answered with nothing", () => {
    const view = mount({ local: null, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change()));
    view.rerender({ local: null, stored: kept, fetchedAt: 1 });
    expect(view.result.current.held).toBe(true);

    view.rerender({ local: null, stored: null, fetchedAt: 3 });
    expect(view.result.current.held).toBe(false);

    act(() => view.result.current.reload());
    expect(adopt).not.toHaveBeenCalled();
  });

  it("ignores another row, another kind, and this reader's own console saves", () => {
    const view = mount({ local: kept, stored: kept, fetchedAt: 1 });

    act(() => {
      announceChange(change({ id: "agent-2" }));
      announceChange(change({ resource: "skill" }));
      announceChange(change({ surface: "console", actor_user_id: ME }));
    });

    expect(view.result.current.held).toBe(false);
  });

  it("treats the reader's own change through another surface as a change elsewhere", () => {
    const view = mount({ local: kept, stored: kept, fetchedAt: 1 });

    act(() => announceChange(change({ surface: "assistant", actor_user_id: ME })));

    expect(view.result.current.held).toBe(true);
  });
});
