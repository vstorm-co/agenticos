import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import { LocalCodingControl } from "./local-coding-control";

const env = vi.hoisted(() => ({ linked: true, link: vi.fn() }));
vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({ data: { linked: env.linked } }),
  useDeviceLink: () => ({ link: { mutateAsync: env.link } }),
  useLocalAgents: () => ({ state: { data: [] } }),
}));

function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LocalCodingControl />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  env.linked = true;
  env.link.mockReset();
  useConversationStore.setState({ currentConversationId: "coding-chat" });
  useWorkOnStore.setState({ byConversation: {}, codingByConversation: {}, draftCoding: null });
});

it("can enable a coding harness without an agent capability and restore the agent setting", async () => {
  const user = userEvent.setup();
  view();
  const select = screen.getByRole("combobox", { name: "Coding agent" });
  await user.selectOptions(select, "codex");
  await waitFor(() => expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("codex"));
  expect(screen.getByText(/Choose a folder under Work on/)).toBeInTheDocument();
  expect(useWorkOnStore.getState().codingFor("another-chat")).toBeNull();
  await user.selectOptions(select, "agent");
  await waitFor(() => expect(useWorkOnStore.getState().codingFor("coding-chat")).toBeNull());
});

it("requires successful pairing before enabling a coding harness", async () => {
  env.linked = false;
  env.link.mockResolvedValue({ linked: false });
  const user = userEvent.setup();
  view();
  await user.selectOptions(screen.getByRole("combobox"), "claude_code");
  await waitFor(() => expect(env.link).toHaveBeenCalledOnce());
  expect(useWorkOnStore.getState().codingFor("coding-chat")).toBeNull();
});

it("does not ask for another folder when this chat has a full-access folder", () => {
  useWorkOnStore.getState().set("coding-chat", { folder: "/approved", mode: "full_access" });
  useWorkOnStore.getState().setCoding("coding-chat", "claude_code");
  view();
  expect(screen.queryByText(/Choose a folder under Work on/)).toBeNull();
});
