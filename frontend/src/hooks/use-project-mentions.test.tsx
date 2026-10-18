import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useProjectMentions } from "./use-project-mentions";

const useProjects = vi.fn();
vi.mock("./use-projects", () => ({ useProjects: (query: unknown) => useProjects(query) }));

const LAUNCH = { id: "p-1", name: "Launch", description: "Q4", default_agent_id: "a-9" };
const NOTES = { id: "p-2", name: "Notes", description: null, default_agent_id: null };

beforeEach(() => {
  useProjects.mockReset().mockReturnValue({ projects: [LAUNCH, NOTES] });
  useConversationStore.getState().setPendingProjectId(null);
  useAgentSelectionStore.getState().select("a-1");
});

describe("useProjectMentions", () => {
  it("offers the reader's projects only while the chat can still choose one", () => {
    const { result, rerender } = renderHook(({ on }) => useProjectMentions(on), {
      initialProps: { on: true },
    });
    expect(useProjects).toHaveBeenLastCalledWith({ limit: 100, enabled: true });
    expect(result.current.items).toEqual([
      { kind: "project", id: "p-1", name: "Launch", detail: "Q4" },
      { kind: "project", id: "p-2", name: "Notes", detail: null },
    ]);

    rerender({ on: false });
    expect(result.current.items).toEqual([]);
  });

  it("starts the chat in the picked project, with its default agent where it has one", () => {
    const { result } = renderHook(() => useProjectMentions(true));

    act(() => result.current.pick("p-1"));
    expect(useConversationStore.getState().pendingProjectId).toBe("p-1");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-9");

    act(() => result.current.pick("p-2"));
    expect(useConversationStore.getState().pendingProjectId).toBe("p-2");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-9");
  });
});
