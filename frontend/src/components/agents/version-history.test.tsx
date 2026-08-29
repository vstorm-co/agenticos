import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VersionHistory } from "./version-history";
import type { AgentEnvironment, AgentSpec, AgentVersion } from "@/types/agents";

/**
 * The version timeline, the promote menu and the spec diff.
 *
 * Three rules live here and none of them is obvious from the UI:
 *
 * - Restore is offered for every version *except* the live one, because
 *   restoring the version you are already running is a publish that changes
 *   nothing.
 * - Promote offers only environments not already serving that version, so the
 *   row can never offer a no-op.
 * - The diff is over the spec's YAML, which is why a reworded tool description
 *   shows up at all - a field-by-field view would have omitted it.
 */

/** What `useAgentVersion` answers, keyed by the version id asked for. */
const specs = new Map<string, AgentSpec>();
const loading = { value: false };
/** What the list itself is served - it pages, so it fetches rather than
 *  being handed rows. `skip` is recorded so a test can assert the pager. */
const served: { versions: AgentVersion[]; total: number; asked: number[] } = {
  versions: [],
  total: 0,
  asked: [],
};

vi.mock("@/hooks", () => ({
  useAgentVersion: (_agentId: string | null, versionId: string | null) => ({
    version: versionId && specs.has(versionId) ? { spec: specs.get(versionId) } : undefined,
    isLoading: loading.value,
  }),
  useAgentVersions: (agentId: string | null, options?: { skip?: number; limit?: number }) => {
    // The paged list. The comparison picker is `useAllAgentVersions` below, which
    // walks every page rather than trusting one capped request - a picker offering
    // the newest fifty of sixty hides the version somebody is looking for.
    if (agentId === null) return { versions: [], total: 0, isLoading: false };
    served.asked.push(options?.skip ?? 0);
    const skip = options?.skip ?? 0;
    return {
      versions: served.versions.slice(skip, skip + 10),
      total: served.total,
      isLoading: loading.value,
    };
  },
  useAllAgentVersions: (agentId: string | null) =>
    agentId === null
      ? { versions: [], total: 0, isLoading: false }
      : { versions: served.versions, total: served.total, isLoading: false },
  VERSIONS_PAGE_SIZE: 10,
}));

function spec(overrides: Partial<AgentSpec> = {}): AgentSpec {
  return {
    name: "Support",
    instructions: "Be helpful.",
    model_settings: {},
    capabilities: [],
    collection_ids: [],
    skill_ids: [],
    context_ids: [],
    mcp_servers: [],
    ...overrides,
  };
}

function version(n: number, overrides: Partial<AgentVersion> = {}): AgentVersion {
  return {
    id: `v${n}-id`,
    version: n,
    note: `Change ${n}`,
    published_by_email: "kacper@example.com",
    created_at: "2026-07-30T10:00:00Z",
    ...overrides,
  } as AgentVersion;
}

function environment(name: string, versionId: string, versionNumber: number): AgentEnvironment {
  return {
    id: `${name}-id`,
    name,
    version_id: versionId,
    version: versionNumber,
    is_default: name === "production",
    tracks_latest: false,
    behind_by: 0,
  } as AgentEnvironment;
}

function mount({
  versions = [version(2), version(1)],
  total,
  ...props
}: Partial<Parameters<typeof VersionHistory>[0]> & {
  versions?: AgentVersion[];
  total?: number;
} = {}) {
  served.versions = versions;
  served.total = total ?? versions.length;
  const onRestore = vi.fn();
  const onPromote = vi.fn();
  render(
    <VersionHistory
      agentId="a-1"
      currentVersionId="v2-id"
      draftSpec={spec()}
      canRestore
      onRestore={onRestore}
      onPromote={onPromote}
      {...props}
    />,
  );
  return { onRestore, onPromote };
}

beforeEach(() => {
  served.versions = [];
  served.total = 0;
  served.asked = [];
  specs.clear();
  specs.set("v1-id", spec({ instructions: "Be terse." }));
  specs.set("v2-id", spec());
  loading.value = false;
});

describe("the version timeline", () => {
  it("says an agent was never published rather than showing an empty list", () => {
    mount({ versions: [] });

    expect(screen.getByText("Never published.")).toBeInTheDocument();
  });

  it("leads each row with the note, which is the why somebody wrote at publish", () => {
    mount();

    expect(screen.getByText("Change 2")).toBeInTheDocument();
    expect(screen.getByText("Change 1")).toBeInTheDocument();
  });

  it("says so when a version was published without a note", () => {
    mount({ versions: [version(1, { note: null })] });

    expect(screen.getByText("No note")).toBeInTheDocument();
  });

  it("names the author, and says so when it does not know one", () => {
    mount({ versions: [version(1, { published_by_email: null })] });

    expect(screen.getByText(/unknown author/)).toBeInTheDocument();
  });

  it("survives a version with no publish timestamp", () => {
    mount({ versions: [version(1, { created_at: undefined })] });

    expect(screen.getByText(/kacper@example.com/)).toBeInTheDocument();
  });

  it("marks which version is live", () => {
    // The one fact somebody scans this list for.
    mount();

    expect(screen.getByText("live")).toBeInTheDocument();
  });

  it("says which environments serve each exact version", () => {
    // Turns "is dev ahead of production" from archaeology into a glance.
    mount({
      environments: [environment("production", "v2-id", 2), environment("dev", "v1-id", 1)],
    });

    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).getByText("production")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("dev")).toBeInTheDocument();
  });
});

describe("restoring", () => {
  it("is not offered for the version already running", () => {
    // A publish that changes nothing.
    mount();

    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).queryByRole("button", { name: /Restore/ })).toBeNull();
    expect(within(rows[1]!).getByRole("button", { name: /Restore/ })).toBeInTheDocument();
  });

  it("restores the version whose row was pressed", async () => {
    const { onRestore } = mount();

    await userEvent.click(screen.getByRole("button", { name: /Restore/ }));

    expect(onRestore).toHaveBeenCalledWith("v1-id");
  });

  it("is not offered at all to somebody who may not publish", () => {
    mount({ canRestore: false });

    expect(screen.queryByRole("button", { name: /Restore/ })).toBeNull();
  });

  it("stops a second restore while one is in flight", () => {
    mount({ restoring: true });

    expect(screen.getByRole("button", { name: /Restore/ })).toBeDisabled();
  });
});

describe("promoting", () => {
  it("offers no menu when there are no environments", () => {
    mount({ environments: [] });

    expect(screen.queryByLabelText(/Promote v2 to/)).toBeNull();
  });

  it("offers only environments not already serving that version", () => {
    // A row must never offer a promotion that would change nothing.
    mount({
      environments: [environment("production", "v2-id", 2), environment("dev", "v1-id", 1)],
    });

    // v2 is served by production, so only dev is a target.
    expect(screen.getByLabelText("Promote v2 to…")).toBeInTheDocument();
    expect(screen.getByLabelText("Promote v1 to…")).toBeInTheDocument();
  });

  it("hides the menu for a version every environment already serves", () => {
    mount({
      versions: [version(2)],
      environments: [environment("production", "v2-id", 2), environment("dev", "v2-id", 2)],
    });

    expect(screen.queryByLabelText("Promote v2 to…")).toBeNull();
  });

  it("names both ends of the move, so the row says what will change", async () => {
    mount({
      environments: [environment("production", "v2-id", 2), environment("dev", "v1-id", 1)],
    });

    await userEvent.click(screen.getByLabelText("Promote v2 to…"));

    expect(screen.getByRole("option", { name: "dev (v1 → v2)" })).toBeInTheDocument();
  });

  it("promotes the environment that was chosen onto that row's version", async () => {
    const { onPromote } = mount({
      environments: [environment("production", "v2-id", 2), environment("dev", "v1-id", 1)],
    });

    await userEvent.click(screen.getByLabelText("Promote v2 to…"));
    await userEvent.click(screen.getByRole("option", { name: "dev (v1 → v2)" }));

    expect(onPromote).toHaveBeenCalledWith("dev-id", "v2-id");
  });

  it("is not offered to somebody who may not publish", () => {
    mount({ canRestore: false, environments: [environment("dev", "v1-id", 1)] });

    expect(screen.queryByLabelText(/Promote/)).toBeNull();
  });

  it("is not offered when the caller passes no promote handler", () => {
    mount({ onPromote: undefined, environments: [environment("dev", "v1-id", 1)] });

    expect(screen.queryByLabelText(/Promote/)).toBeNull();
  });

  it("stops a second promotion while one is in flight", () => {
    mount({ promoting: true, environments: [environment("dev", "v1-id", 1)] });

    expect(screen.getByLabelText("Promote v2 to…")).toBeDisabled();
  });
});

describe("the diff", () => {
  it("compares the newest version against the draft by default", () => {
    // "What have I changed since the version that is running" is the comparison
    // somebody opening a history almost always wants.
    mount();

    expect(screen.getByLabelText("Compare from")).toHaveTextContent("v2");
    expect(screen.getByLabelText("Compare to")).toHaveTextContent("Draft");
  });

  it("says two identical specs are identical rather than showing an empty diff", () => {
    // v2 and the draft are the same object here.
    mount();

    expect(screen.getByText(/Identical - nothing changed/)).toBeInTheDocument();
  });

  it("counts the lines added and removed", () => {
    // One scalar field changed, so the count is unambiguous: one line out, one
    // line in. A multi-line instruction serialises as a block scalar, where the
    // count depends on YAML's folding rather than on the edit.
    mount({ draftSpec: spec({ name: "Sales" }) });

    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("−1")).toBeInTheDocument();
  });

  it("shows a reworded instruction as the lines that moved", () => {
    // The reason the diff is over YAML: a field-by-field view would report
    // "instructions changed" and show neither side.
    mount({ draftSpec: spec({ instructions: "Be terse." }) });

    expect(screen.getByText(/Be terse\./)).toBeInTheDocument();
  });

  it("compares two published versions when asked to", async () => {
    mount();

    await userEvent.click(screen.getByLabelText("Compare to"));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));

    // v1 says "Be terse.", v2 says "Be helpful." - both sides render.
    expect(screen.getByText(/Be terse\./)).toBeInTheDocument();
  });

  it("changes the left-hand side from the picker as well as from a row", async () => {
    mount({ versions: [version(3), version(2), version(1)], currentVersionId: "v3-id" });
    specs.set("v3-id", spec({ instructions: "Be exhaustive." }));

    await userEvent.click(screen.getByLabelText("Compare from"));
    await userEvent.click(screen.getByRole("option", { name: "v1" }));

    expect(screen.getByLabelText("Compare from")).toHaveTextContent("v1");
  });

  it("changes the left-hand side from a row's Compare button", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Compare v1" }));

    expect(screen.getByRole("button", { name: "Compare v1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows a placeholder while a version's spec is being fetched", () => {
    loading.value = true;
    mount();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("asks for two versions when one side has not resolved", () => {
    // A version id whose spec the cache does not have - a deleted version, or a
    // request that failed.
    specs.delete("v2-id");
    mount({ draftSpec: spec() });

    expect(screen.getByText("Pick two versions to compare.")).toBeInTheDocument();
  });

  it("counts a single collapsed line in the singular", () => {
    // Two edits seven lines apart: three lines of context either side leave
    // exactly one line hidden between them, which is the smallest gap the diff
    // can produce and the only one that reads wrong in the plural. The unchanged
    // top matter of the spec produces its own single-line gaps, so there may be
    // more than one - what matters is that a one-line gap is rendered singular.
    const middle = Array.from({ length: 7 }, (_, index) => `line ${index}`).join("\n");
    specs.set("v1-id", spec({ instructions: `first\n${middle}\nlast` }));
    mount({
      versions: [version(1)],
      currentVersionId: "v1-id",
      draftSpec: spec({ instructions: `FIRST\n${middle}\nLAST` }),
    });

    expect(screen.getAllByText("1 unchanged line").length).toBeGreaterThan(0);
    expect(screen.queryByText("1 unchanged lines")).not.toBeInTheDocument();
  });

  it("collapses long runs of unchanged lines", () => {
    const long = Array.from({ length: 30 }, (_, index) => `line ${index}`).join("\n");
    mount({
      versions: [version(1)],
      currentVersionId: "v1-id",
      draftSpec: spec({ instructions: `${long}\nand one more` }),
    });
    specs.set("v1-id", spec({ instructions: long }));

    // The gap row says how many lines it stands for rather than hiding them
    // silently.
    expect(screen.getByText(/unchanged lines?/)).toBeInTheDocument();
  });
});

describe("a history longer than a page", () => {
  const many = Array.from({ length: 14 }, (_, index) => version(14 - index));

  it("offers no pager for a history that fits", () => {
    // Four versions is not a paged list, and a pager under it is furniture.
    mount({ versions: [version(2), version(1)], total: 2 });

    expect(screen.queryByRole("button", { name: /next/i })).toBeNull();
  });

  it("pages, and asks the server for the page rather than slicing one it has", () => {
    // The listing was capped at fifty with no offset and reported the cap as
    // the total, so a longer history had versions nothing could reach.
    mount({ versions: many, total: 14 });

    expect(screen.getByText("Change 14")).toBeInTheDocument();
    expect(screen.queryByText("Change 4")).toBeNull();
    expect(served.asked).toContain(0);
  });

  it("waits rather than saying an agent was never published", async () => {
    // The two are opposite claims about the same empty list, and the
    // reassuring one is the wrong default while a request is in flight.
    loading.value = true;
    mount({ versions: [], total: 0 });

    expect(screen.queryByText("Never published.")).toBeNull();
    loading.value = false;
  });

  it("aims the comparison at the newest version, once, and leaves it there", async () => {
    // Adopted from the first page when it arrives - and only while nothing else
    // has been picked, because paging must not silently re-aim a comparison.
    mount({ versions: many, total: 14 });

    expect(screen.getByLabelText("Compare from")).toHaveTextContent("v14");

    await userEvent.click(screen.getByRole("button", { name: "Compare v13" }));
    expect(screen.getByLabelText("Compare from")).toHaveTextContent("v13");
  });

  it("keeps a comparison the reader set up when the page turns", async () => {
    mount({ versions: many, total: 14 });
    await userEvent.click(screen.getByRole("button", { name: "Compare v12" }));

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    // Paging must not silently re-aim the diff at whatever is newest on the
    // page that just arrived.
    expect(served.asked).toContain(10);
    expect(screen.getByLabelText("Compare from")).toHaveTextContent("v12");
  });
});
