import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { LocalSkill } from "@/lib/desktop/commands";
import { useWorkOnStore } from "@/stores/work-on-store";
import { LocalSkillsControl } from "./local-skills-control";

const env = vi.hoisted(() => ({
  linked: true,
  link: vi.fn(),
  skills: [] as LocalSkill[],
}));

vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({ data: { linked: env.linked, connected: env.linked } }),
  useDeviceLink: () => ({ link: { mutateAsync: env.link } }),
  useLocalSkills: () => ({ data: env.skills }),
}));
vi.mock("@/stores", () => ({
  useConversationStore: (select: (state: { currentConversationId: string }) => unknown) =>
    select({ currentConversationId: "c1" }),
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: { getState: () => ({ user: { id: "u1" } }) },
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: { getState: () => ({ activeOrgId: "o1" }) },
}));

const skill = (
  name: string,
  source: LocalSkill["source"],
  shadowed_by: LocalSkill["shadowed_by"] = null,
): LocalSkill => ({ name, description: "d", source, shadowed_by });

beforeEach(() => {
  env.linked = true;
  env.link.mockReset();
  env.skills = [
    skill("a", "agents"),
    skill("b", "agents"),
    skill("c", "claude"),
    skill("a", "codex", "agents"),
  ];
  useWorkOnStore.setState({ skillsByConversation: {}, draftSkills: [] });
});

function mount() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      <LocalSkillsControl />
    </QueryClientProvider>,
  );
}

const chosen = () => useWorkOnStore.getState().skillsFor("c1");

it("is off for a new chat, and says so, with what each folder holds", () => {
  mount();
  expect(screen.getByRole("checkbox", { name: /~\/\.agents\/skills/ })).not.toBeChecked();
  expect(screen.getByText("2 skills")).toBeInTheDocument();
  expect(screen.getByText("1 skill")).toBeInTheDocument();
  expect(screen.getByText("0 skills")).toBeInTheDocument();
  expect(screen.getByText(/Off: this chat uses only what is in AgenticOS/)).toBeInTheDocument();
  expect(screen.getByText(/1 skill is hidden by one of the same name/)).toBeInTheDocument();
});

it("turns sources on and off one at a time, in the order that settles a clash", async () => {
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("checkbox", { name: /~\/\.codex\/skills/ }));
  await waitFor(() => expect(chosen()).toEqual(["codex"]));
  await user.click(screen.getByRole("checkbox", { name: /~\/\.agents\/skills/ }));
  await waitFor(() => expect(chosen()).toEqual(["agents", "codex"]));
  await user.click(screen.getByRole("checkbox", { name: /~\/\.codex\/skills/ }));
  await waitFor(() => expect(chosen()).toEqual(["agents"]));
  expect(screen.getByText(/follows your AGENTS\.md/)).toBeInTheDocument();
});

it("links this computer first when it is not linked, and stays off if that is refused", async () => {
  env.linked = false;
  env.link.mockResolvedValue({ linked: false });
  const user = userEvent.setup();
  mount();
  await user.click(screen.getByRole("checkbox", { name: /~\/\.claude\/skills/ }));
  await waitFor(() => expect(env.link).toHaveBeenCalledOnce());
  expect(chosen()).toEqual([]);
  env.link.mockResolvedValue({ linked: true });
  await user.click(screen.getByRole("checkbox", { name: /~\/\.claude\/skills/ }));
  await waitFor(() => expect(chosen()).toEqual(["claude"]));
});

it("a draft chat's choice moves under its id when the chat is filed", () => {
  useWorkOnStore.getState().setSkills(null, ["claude"]);
  expect(useWorkOnStore.getState().skillsFor(null)).toEqual(["claude"]);
  useWorkOnStore.getState().adopt("c1");
  expect(chosen()).toEqual(["claude"]);
  expect(useWorkOnStore.getState().skillsFor(null)).toEqual([]);
  useWorkOnStore.getState().setSkills(null, ["codex"]);
  useWorkOnStore.getState().resetDraft();
  expect(useWorkOnStore.getState().skillsFor(null)).toEqual([]);
});
