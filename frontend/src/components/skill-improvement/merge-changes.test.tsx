import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { skillSession } from "@/test-utils/skill-improvement";
import type { MergeFile, MergeText, SkillMerge } from "@/types/skill-merge";
import { MergeChanges } from "./merge-changes";

const merges = vi.hoisted(() => ({
  merge: undefined as SkillMerge | undefined,
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  editDescription: { mutateAsync: vi.fn(), isPending: false },
  editPart: { mutateAsync: vi.fn(), isPending: false },
  pickFile: { mutateAsync: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-skill-merge", () => ({ useSkillMerge: () => merges }));

const text = (overrides: Partial<MergeText>): MergeText => ({
  state: "same",
  base: "one\n",
  fork: "one\n",
  main: "one\n",
  result: "one\n",
  proposed: null,
  edited: false,
  ...overrides,
});

const file = (overrides: Partial<MergeFile>): MergeFile => ({
  name: "a.md",
  state: "same",
  base: { description: null, size_bytes: 5 },
  fork: { description: null, size_bytes: 5 },
  main: { description: null, size_bytes: 5 },
  take: "main",
  ...overrides,
});

function merge(overrides: Partial<SkillMerge> = {}): SkillMerge {
  return {
    id: "m1",
    run_id: "s1",
    skill_id: "k1",
    fork_id: "f1",
    kind: "catch_up",
    base: { id: "b", number: 5 },
    fork: { id: "f", number: 2 },
    main: { id: "m", number: 7 },
    description: text({ base: "Refunds.", fork: "Refunds.", main: "Refunds.", result: "Refunds." }),
    parts: [
      text({ base: "one\ntwo\n", fork: "one\ntwo\n", main: "one\ntwo\n", result: "one\ntwo\n" }),
      text({ state: "fork", base: "three\n", fork: "THREE\n", main: "three\n", result: "THREE\n" }),
      text({
        state: "conflict",
        base: "four",
        fork: "four, by fork",
        main: "four, by main",
        result: null,
      }),
    ],
    files: [
      file({}),
      file({ name: "b.md", state: "conflict", fork: null, take: null }),
      file({ name: "c.md", state: "main", fork: null, base: null, take: "main" }),
    ],
    conflicts: 1,
    unresolved: 2,
    updated_at: null,
    ...overrides,
  };
}

function mount(editable = true) {
  return render(
    <MergeChanges session={skillSession({ line_name: "returns" })} editable={editable} />,
  );
}

beforeEach(() => {
  merges.merge = merge();
  merges.isLoading = false;
  merges.error = null;
  for (const action of [merges.editDescription, merges.editPart, merges.pickFile]) {
    action.mutateAsync = vi.fn().mockResolvedValue(merge());
    action.isPending = false;
  }
});

describe("MergeChanges", () => {
  it("says what it merges and marks what waits for a person", () => {
    mount();

    expect(
      screen.getByText("Takes main v7 into “returns” v2. Both started from main v5."),
    ).toBeVisible();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "2 parts wait for you. The check starts once they are settled.",
    );
    expect(alert).toHaveTextContent(
      "The assistant could not write a text for 1 conflict, so it is left for you.",
    );
    expect(screen.getByText("The description is the same on both sides.")).toBeVisible();
    expect(screen.getByText("2 lines neither side changed")).toBeVisible();
    const taken = screen.getByRole("region", { name: "Part 2" });
    expect(within(taken).getByText("From the fork")).toBeVisible();
    const conflict = screen.getByRole("region", { name: "Part 3" });
    expect(within(conflict).getByText("Waits for you")).toBeVisible();
    expect(within(conflict).getByText("four, by fork")).toBeVisible();
  });

  it("saves a person's text for a conflict, and keeps it on screen when refused", async () => {
    mount();
    const box = screen.getByRole("textbox", { name: "Merged text of Part 3" });
    const save = within(screen.getByRole("region", { name: "Part 3" })).getByRole("button", {
      name: "Save",
    });
    expect(save).toBeDisabled();

    await userEvent.type(box, "four, by both");
    await userEvent.click(save);
    expect(merges.editPart.mutateAsync).toHaveBeenCalledWith({
      index: 2,
      result: "four, by both",
    });
    expect(box).toHaveValue("");

    merges.editPart.mutateAsync = vi.fn().mockRejectedValue(new ApiError(400, "Not at Changes"));
    await userEvent.type(box, "again");
    await userEvent.click(save);
    expect(await screen.findByText("Not at Changes")).toBeVisible();
    expect(box).toHaveValue("again");
  });

  it("shows the assistant's text, a person's rewrite, and a changed description", async () => {
    merges.merge = merge({
      description: text({
        state: "conflict",
        base: "Refunds.",
        fork: "Refunds, the fork's way.",
        main: "Refunds, main's way.",
        result: "Refunds, both ways.",
        proposed: "Refunds, both ways.",
      }),
      parts: [
        text({
          state: "conflict",
          result: "mine\n",
          proposed: "theirs\n",
          edited: true,
        }),
      ],
      files: [],
      conflicts: 2,
      unresolved: 0,
    });
    mount();

    expect(
      screen.getByText("All 2 conflicts are settled. Read them before you check the merge."),
    ).toBeVisible();
    expect(screen.getByText("The assistant's text")).toBeVisible();
    expect(screen.getByText("Your text")).toBeVisible();
    const box = screen.getByRole("textbox", { name: "Merged text of Description" });
    expect(box).toHaveValue("Refunds, both ways.");
    expect(box).toHaveAttribute("maxlength", "500");
    await userEvent.clear(box);
    expect(
      within(screen.getByRole("region", { name: "Description" })).getByRole("button", {
        name: "Save",
      }),
    ).toBeDisabled();
    await userEvent.type(box, "Refunds.");
    await userEvent.click(
      within(screen.getByRole("region", { name: "Description" })).getByRole("button", {
        name: "Save",
      }),
    );
    expect(merges.editDescription.mutateAsync).toHaveBeenCalledWith("Refunds.");
  });

  it("keeps one side of a file both changed, dropping it where that side did", async () => {
    const view = mount();

    const files = screen.getByRole("region", { name: "Files" });
    expect(within(files).getByText("Both sides changed it. Keep one side.")).toBeVisible();
    expect(within(files).getByText("Main's version is kept")).toBeVisible();
    await userEvent.click(within(files).getByRole("button", { name: "Drop it, as the fork did" }));
    expect(merges.pickFile.mutateAsync).toHaveBeenCalledWith({ name: "b.md", take: "fork" });
    expect(within(files).getByRole("button", { name: "Keep main's" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    merges.merge = merge({
      files: [file({ name: "b.md", state: "conflict", fork: null, take: "fork" })],
    });
    view.rerender(<MergeChanges session={skillSession({ line_name: "returns" })} editable />);
    expect(screen.getByRole("button", { name: "Drop it, as the fork did" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("lets a person rewrite a part one side changed, too", async () => {
    mount();
    const taken = screen.getByRole("region", { name: "Part 2" });
    const box = within(taken).getByRole("textbox", { name: "Merged text of Part 2" });
    expect(box).toHaveValue("THREE\n");

    await userEvent.clear(box);
    await userEvent.type(box, "Three");
    await userEvent.click(within(taken).getByRole("button", { name: "Save" }));

    expect(merges.editPart.mutateAsync).toHaveBeenCalledWith({ index: 1, result: "Three" });
  });

  it("is read only once the session left Changes", () => {
    merges.merge = merge({
      parts: [
        text({ state: "conflict", result: "four\n", proposed: "four\n" }),
        text({ state: "main", base: "five\n", fork: "five\n", main: "FIVE\n", result: "FIVE\n" }),
      ],
      files: [file({ name: "b.md", state: "conflict", fork: null, take: "fork" })],
      unresolved: 0,
    });
    mount(false);
    expect(within(screen.getByRole("region", { name: "Part 2" })).getByText("FIVE")).toBeVisible();

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("Dropped, as on the fork")).toBeVisible();
  });

  it("says when nothing conflicted, and names an open conflict nobody may settle here", () => {
    merges.merge = merge({
      parts: [text({ state: "conflict", result: null, proposed: "x\n" })],
      files: [],
      conflicts: 0,
      unresolved: 1,
    });
    const view = mount(false);
    expect(screen.getByText("Not settled yet.")).toBeVisible();
    expect(screen.queryByText(/could not write a text/)).not.toBeInTheDocument();

    merges.merge = merge({
      parts: [text({ base: "last", fork: "last", main: "last", result: "last" })],
      files: [],
      conflicts: 0,
      unresolved: 0,
    });
    view.rerender(<MergeChanges session={skillSession()} editable />);
    expect(
      screen.getByText("Nothing conflicts: each part takes the side that changed it."),
    ).toBeVisible();
    expect(screen.getByText("1 line neither side changed")).toBeVisible();
  });

  it("waits for the merge, and says why it could not be read", async () => {
    merges.merge = undefined;
    merges.isLoading = true;
    const view = mount();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    merges.isLoading = false;
    merges.error = new ApiError(503, "The service is busy");
    view.rerender(<MergeChanges session={skillSession()} editable />);
    expect(screen.getByText("The service is busy")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
    expect(merges.refetch).toHaveBeenCalled();
  });
});
