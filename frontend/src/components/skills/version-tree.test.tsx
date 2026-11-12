import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render as renderBare, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { SkillAgentUsage } from "@/types/skill-versions";
import { VersionTree } from "./version-tree";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderBare(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

function onMain(name: string): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      state: "main",
      version: { id: "m25", number: 25, fork_id: null },
      fork: null,
      behind_main: 0,
    },
    agent_version: 1,
    environments: [],
    draft_differs: false,
    can_change: false,
    can_publish: false,
  };
}

describe("VersionTree", () => {
  it("fits a single version instead of reserving a large empty canvas", () => {
    const { container } = render(
      <VersionTree skillId="s1" mainLatest={1} forks={[]} agents={[]} error={null} />,
    );
    const canvas = container.querySelector<HTMLElement>("[style*='transform']")!;
    expect(canvas.parentElement!.style.height).toBe("128px");
  });

  it("folds the versions nobody uses and unfolds them on request", async () => {
    render(<VersionTree skillId="s1" mainLatest={25} forks={[]} agents={[]} error={null} />);

    expect(screen.getByText("v25")).toBeInTheDocument();
    expect(screen.queryByText("v12")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "23 versions (v24–v2)" }));

    expect(screen.getByText("v12")).toBeInTheDocument();
  });

  it("opens on main's newest version at the right, zooms, and goes back there on reset", async () => {
    const { container } = render(
      <VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />,
    );
    const canvas = () => container.querySelector<HTMLElement>("[style*='transform']")!;
    // Three boxes and the room around them, drawn in a viewport jsdom gives no width.
    expect(canvas().style.transform).toBe("translate(-712px, 0px) scale(1)");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(canvas().style.transform).toBe("translate(-712px, 0px) scale(1)");
  });

  it("compares a version pressed on the canvas, and pans when the press drags it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 3 });
    const { container } = render(
      <VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />,
    );
    const canvas = container.querySelector<HTMLElement>("[style*='transform']")!;
    const viewport = canvas.parentElement!;
    const capture = vi.fn();
    viewport.setPointerCapture = capture;
    const compare = screen.getByRole("button", { name: "Compare v2" });
    const before = canvas.style.transform;

    // A real press that stays put: down, up and the click, on the button under the canvas.
    await userEvent.pointer([{ keys: "[MouseLeft]", target: compare }]);
    expect(capture).not.toHaveBeenCalled();
    expect(compare).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "v2" })).toBeInTheDocument();
    // The box's own name keeps the row: the control beside it is an icon, its words a tooltip.
    expect(compare).toHaveTextContent("");
    expect(compare).toHaveAttribute("title", "Comparing");
    expect(screen.getByTitle("v3")).toHaveTextContent("v3");

    const press = (type: string, x: number) => {
      const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: 10 });
      Object.defineProperty(event, "pointerId", { value: 7 });
      fireEvent(compare, event);
    };
    press("pointerdown", 10);
    press("pointermove", 60);
    expect(capture).toHaveBeenCalledWith(7);
    expect(canvas.style.transform).not.toBe(before);
  });

  it("names every agent in the box of the version it reads", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[]}
        agents={["Ana", "Bo", "Cy", "Di", "Ed"].map(onMain)}
        error={null}
      />,
    );

    const newest = screen.getByText("v25").closest("li")!;
    for (const name of ["Ana", "Bo", "Cy", "Di", "Ed"]) {
      expect(within(newest).getByText(name)).toBeInTheDocument();
    }
  });

  it("puts the versions picked side by side, and takes them out again", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) {
        return {
          items: [
            { id: "m25", number: 25 },
            { id: "m1", number: 1 },
          ],
          total: 25,
        };
      }
      if (url.endsWith("/m1")) {
        return { id: "m1", number: 1, description: "First", content: "Start.", resources: [] };
      }
      return {
        id: "m25",
        number: 25,
        description: "Refunds, by the book",
        content: "Answer from the policy.",
        resources: [
          { name: "policy.md", description: "The policy", size_bytes: 1, digest: "d" },
          { name: "notes.md", description: null, size_bytes: 1, digest: "e" },
        ],
      };
    });
    render(<VersionTree skillId="s1" mainLatest={25} forks={[]} agents={[]} error={null} />);

    const compare = screen.getByRole("button", { name: "Compare v25" });
    await userEvent.click(compare);
    expect(compare).toHaveAttribute("aria-pressed", "true");
    const column = await screen.findByRole("region", { name: "v25" });
    expect(await within(column).findByText("Answer from the policy.")).toBeVisible();
    expect(within(column).getByText("Refunds, by the book")).toBeVisible();
    expect(within(column).getByText("policy.md")).toBeVisible();
    expect(screen.getByText(/Pick another version/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Compare v1" }));
    expect(screen.getByText("2 versions")).toBeVisible();
    const first = screen.getByRole("region", { name: "v1" });
    expect(await within(first).findByText("policy.md")).toBeVisible();
    expect(within(first).getByText("policy.md").tagName).toBe("DEL");
    await userEvent.click(screen.getByRole("button", { name: "Remove v1 from the comparison" }));
    expect(screen.getByText("1 version")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Compare v25" }));
    expect(screen.queryByText("Comparison")).toBeNull();
  });

  it("marks what each version says differently from the reference, and lets another be it", async () => {
    const versions: Record<string, object> = {
      m3: {
        id: "m3",
        number: 3,
        description: "Refunds by the book",
        content: "Answer from the policy.\nBe brief.",
        resources: [
          { name: "policy.md", description: null, size_bytes: 1, digest: "a" },
          { name: "old.md", description: null, size_bytes: 1, digest: "o" },
        ],
      },
      m2: {
        id: "m2",
        number: 2,
        description: "Refunds by the book",
        content: "Answer from the handbook.\nBe brief.",
        resources: [
          { name: "policy.md", description: null, size_bytes: 1, digest: "b" },
          { name: "new.md", description: null, size_bytes: 1, digest: "n" },
        ],
      },
    };
    vi.mocked(apiClient.get).mockImplementation(async (url: string) =>
      url.includes("/versions?")
        ? {
            items: [
              { id: "m3", number: 3 },
              { id: "m2", number: 2 },
            ],
            total: 3,
          }
        : versions[url.split("/").pop()!],
    );
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v3" }));
    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    const reference = await screen.findByRole("region", { name: "v3" });
    const other = screen.getByRole("region", { name: "v2" });
    expect(within(reference).getByText("Reference")).toBeVisible();
    const shown = await within(reference).findByText(/Answer from the policy/);
    expect(shown.closest("table")).not.toBeNull();

    expect(await within(other).findByText("handbook", { selector: "ins" })).toBeVisible();
    expect(within(other).getByText("policy", { selector: "del" })).toBeVisible();
    expect(within(other).getByText("same as the reference")).toBeVisible();
    expect(within(other).getByText("new.md").closest("li")).toHaveTextContent("added");
    expect(within(other).getByText("policy.md").closest("li")).toHaveTextContent("changed");
    expect(within(other).getByText("old.md").tagName).toBe("DEL");

    await userEvent.click(screen.getByRole("checkbox", { name: "Only the differences" }));
    expect(within(other).queryByText("Refunds by the book")).toBeNull();
    expect(within(reference).getByText("Refunds by the book")).toBeVisible();

    await userEvent.click(within(other).getByRole("button", { name: "Set as reference" }));
    expect(within(other).getByText("Reference")).toBeVisible();
    expect(within(reference).getByText("new.md").tagName).toBe("DEL");
  });

  it("draws the reference first, behind a divider, the others in the order picked", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) =>
      url.includes("/versions?")
        ? {
            items: [3, 2, 1].map((number) => ({ id: `m${number}`, number })),
            total: 3,
          }
        : { description: "Same", content: "Same.", resources: [] },
    );
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);
    for (const number of [3, 1, 2]) {
      await userEvent.click(screen.getByRole("button", { name: `Compare v${number}` }));
    }
    const order = () =>
      screen.getAllByRole("region").map((column) => column.getAttribute("aria-label"));
    expect(order()).toEqual(["v3", "v1", "v2"]);
    expect(screen.getByRole("separator")).toBeInTheDocument();

    const second = screen.getByRole("region", { name: "v2" });
    await userEvent.click(within(second).getByRole("button", { name: "Set as reference" }));
    expect(order()).toEqual(["v2", "v3", "v1"]);
    expect(within(screen.getByRole("region", { name: "v2" })).getByText("Reference")).toBeVisible();

    await userEvent.click(
      within(screen.getByRole("region", { name: "v1" })).getByRole("button", {
        name: "Set as reference",
      }),
    );
    expect(order()).toEqual(["v1", "v3", "v2"]);
  });

  it("keeps the previous reference readable after a version on another line is set", async () => {
    const marketplace = {
      id: "f9",
      skill_id: "s1",
      name: "Marketplace",
      base: { id: "m1", number: 1 },
      started_from: { id: "m1", number: 1 },
      latest: { id: "x1", number: 1 },
      changes: 1,
      behind_main: 1,
      agents: 0,
      archive_candidate: false,
      archived_at: null,
      created_at: "2026-11-01T10:00:00Z",
    };
    const bodies: Record<string, object> = {
      x1: {
        id: "x1",
        number: 1,
        description: "Marketplace rules",
        content: "Sell.",
        resources: [],
      },
      m2: { id: "m2", number: 2, description: "Shop rules", content: "Sell.", resources: [] },
    };
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) {
        const query = new URLSearchParams(url.split("?")[1]);
        // The API refuses a negative skip, as the real one does.
        if (Number(query.get("skip")) < 0) throw new Error("skip must be at least 0");
        return query.get("fork_id") === "f9"
          ? { items: [{ id: "x1", number: 1 }], total: 1 }
          : {
              items: [
                { id: "m2", number: 2 },
                { id: "m1", number: 1 },
              ],
              total: 2,
            };
      }
      return bodies[url.split("/").pop()!];
    });
    render(
      <VersionTree skillId="s1" mainLatest={2} forks={[marketplace]} agents={[]} error={null} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Compare Marketplace v1" }));
    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    await within(screen.getByRole("region", { name: "v2" })).findByText("Shop", {
      selector: "ins",
    });
    await userEvent.click(
      within(screen.getByRole("region", { name: "v2" })).getByRole("button", {
        name: "Set as reference",
      }),
    );

    const previous = screen.getByRole("region", { name: "Marketplace v1" });
    expect(await within(previous).findByText("Marketplace", { selector: "ins" })).toBeVisible();
    expect(within(previous).queryByLabelText("Loading the version…")).toBeNull();
    expect(screen.getByRole("region", { name: "v2" })).toHaveClass("border-primary");
    expect(previous).not.toHaveClass("border-primary");
  });

  it("says a column cannot be marked when its reference cannot be read", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) {
        return {
          items: [
            { id: "m3", number: 3 },
            { id: "m2", number: 2 },
          ],
          total: 3,
        };
      }
      if (url.endsWith("/m3")) throw new Error("Reference is down");
      return { id: "m2", number: 2, description: "Two", content: "Two.", resources: [] };
    });
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v3" }));
    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));

    const other = screen.getByRole("region", { name: "v2" });
    expect(await within(other).findByText(/Reference is down/)).toBeVisible();
  });

  it("says when a compared version cannot be read, and clears the comparison", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Versions are down"));
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    expect(await screen.findByText("Couldn't load this version. Versions are down")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("Comparison")).toBeNull();
  });

  it("finds a compared version that versions saved since have pushed down the list", async () => {
    const page = (from: number, to: number) =>
      Array.from({ length: from - to + 1 }, (_, index) => ({
        id: `m${from - index}`,
        number: from - index,
      }));
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) {
        return { items: url.includes("skip=50") ? page(10, 1) : page(60, 11), total: 60 };
      }
      return { id: "m1", number: 1, description: "First", content: "Start.", resources: [] };
    });
    render(<VersionTree skillId="s1" mainLatest={7} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v1" }));
    const column = await screen.findByRole("region", { name: "v1" });
    expect(await within(column).findByText("Start.")).toBeVisible();
  });

  it("says a compared version is not there any more, and looks again on Retry", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "m3", number: 3 }], total: 3 });
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    expect(await screen.findByText("Couldn't load this version.")).toBeVisible();
    const calls = vi.mocked(apiClient.get).mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(calls));
  });

  it("reads a compared version again on Retry when it could not be fetched", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) return { items: [{ id: "m2", number: 2 }], total: 3 };
      throw new Error("Version is down");
    });
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    expect(await screen.findByText(/Version is down/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(expect.stringMatching(/versions\/m2$/)),
    );
  });
});

describe("VersionTree's forks", () => {
  const fork = (latest: number | null) => ({
    id: "f1",
    skill_id: "s1",
    name: "Returns",
    base: { id: "m3", number: 3 },
    started_from: { id: "m3", number: 3 },
    latest: latest === null ? null : { id: `r${latest}`, number: latest },
    changes: latest ?? 0,
    behind_main: 22,
    agents: 1,
    archive_candidate: false,
    archived_at: null,
    created_at: "2026-11-01T10:00:00Z",
  });
  const onFork = (latest: number | null): SkillAgentUsage => ({
    ...onMain("Refunds"),
    binding: {
      state: "fork",
      version: { id: "r", number: latest ?? 3, fork_id: "f1" },
      fork: { id: "f1", name: "Returns", base_number: 3, changes: latest ?? 0 },
      behind_main: 22,
    },
  });

  it("draws a fork off its base with its own versions and agents", async () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[fork(2)]}
        agents={[onFork(2)]}
        error={null}
      />,
    );

    expect(screen.getByText("Fork “Returns”")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Compare Returns v2" }));
    expect(screen.getByRole("region", { name: "Returns v2" })).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining("fork_id=f1"));
    expect(screen.getByText("2 changes · 22 behind main")).toBeInTheDocument();
    // Main's v2 and the fork's own v2, told apart by the fork's name.
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getAllByText("Returns v2")[0]).toBeInTheDocument();
    expect(screen.getByText("Refunds")).toBeInTheDocument();
  });

  it("holds the agents of a fork with no versions of its own on the branch", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[fork(null)]}
        agents={[onFork(null)]}
        error={null}
      />,
    );

    expect(screen.getByText("no changes yet · 22 behind main")).toBeInTheDocument();
    const branch = screen.getByText("No version of its own yet").closest("li")!;
    expect(within(branch).getByText("Refunds")).toBeInTheDocument();
    expect(within(branch).queryByRole("button", { name: /^Compare/ })).toBeNull();
  });

  it("says when the agents cannot be read instead of drawing an empty tree", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[]}
        agents={[]}
        error={new Error("offline")}
      />,
    );

    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.queryByText("v25")).toBeNull();
  });
});
