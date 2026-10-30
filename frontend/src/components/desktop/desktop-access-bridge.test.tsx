import { act, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { DesktopAccessBridge } from "./desktop-access-bridge";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useProjectFoldersStore } from "@/stores/project-folders-store";

const events = vi.hoisted(() => new Map<string, (value: unknown) => void>());
vi.mock("@/hooks/use-desktop", () => ({
  useShellEvent: (event: string, handler: (value: unknown) => void) => events.set(event, handler),
}));

it("revokes only matching folder or computer grants across drafts, chats and projects", () => {
  const folder = { folder: "/work", mode: "workspace_write" as const };
  const computer = { folder: "/home", mode: "full_access" as const, computer_grant: "grant" };
  useWorkOnStore.setState({ byConversation: { folder, computer, none: null }, draft: folder });
  useProjectFoldersStore.setState({ byProject: { one: folder, two: computer } });
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <DesktopAccessBridge />
    </QueryClientProvider>,
  );
  const send = (value: unknown) => act(() => events.get("desktop:access-changed")?.(value));
  for (const value of [null, "bad", {}, { kind: "other", id: 4, path: 3 }]) send(value);
  expect(useWorkOnStore.getState().draft).toEqual(folder);
  send({ kind: "folder", path: "/work" });
  expect(useWorkOnStore.getState().byConversation).toMatchObject({ folder: null, computer });
  expect(useWorkOnStore.getState().draft).toBeNull();
  expect(useProjectFoldersStore.getState().byProject).toEqual({ two: computer });
  send({ kind: "computer", id: "grant" });
  expect(useWorkOnStore.getState().byConversation.computer).toBeNull();
  expect(useProjectFoldersStore.getState().byProject).toEqual({});
  expect(invalidate).toHaveBeenCalled();
});
