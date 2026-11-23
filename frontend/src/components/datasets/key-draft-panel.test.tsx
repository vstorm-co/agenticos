import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseKeyDraft } from "@/types/datasets";
import { KeyDraftPanel } from "./key-draft-panel";

const hook = {
  draft: null as CaseKeyDraft | null,
  loading: false,
  error: null as Error | null,
  start: vi.fn(),
  starting: false,
  dismiss: vi.fn(),
};
vi.mock("@/hooks/use-case-key-draft", () => ({ useCaseKeyDraft: () => hook }));

const KEYS = Array.from({ length: 7 }, (_, at) => ({ key: `Fact ${at + 1}`, value: `v${at}` }));

function shown(
  draft: CaseKeyDraft | null,
  saved: string | null = "Invoice INV-7",
  edited?: string,
) {
  hook.draft = draft;
  const onUse = vi.fn();
  render(
    <KeyDraftPanel
      datasetId="d1"
      caseId="c1"
      savedReference={saved}
      editedReference={edited ?? saved ?? ""}
      onUse={onUse}
    />,
  );
  return onUse;
}

function draft(status: CaseKeyDraft["status"], keys = KEYS, error: string | null = null) {
  return {
    id: "k1",
    case_id: "c1",
    status,
    keys,
    error,
    created_at: "2026-11-20T00:00:00Z",
    finished_at: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  hook.starting = false;
  hook.loading = false;
  hook.error = null;
});

describe("KeyDraftPanel", () => {
  it("asks for the keys of a saved reference answer", async () => {
    shown(null);
    await userEvent.click(
      screen.getByRole("button", { name: "List keys from the reference answer" }),
    );
    expect(hook.start).toHaveBeenCalled();
  });

  it("waits for a saved reference answer, and for an edited one to be saved", () => {
    shown(null, null);
    expect(
      screen.getByRole("button", { name: "List keys from the reference answer" }),
    ).toBeDisabled();
    expect(screen.getByText("Save a reference answer to list its keys.")).toBeInTheDocument();
  });

  it("does not list an answer edited since it was saved", () => {
    shown(null, "Invoice INV-7", "Invoice INV-8");
    expect(
      screen.getByText("Save the reference answer first: keys are listed from the saved one."),
    ).toBeInTheDocument();
  });

  it("offers nothing until it knows whether the case has a draft", () => {
    hook.loading = true;
    shown(null);
    expect(screen.getByText("Checking for drafted keys…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says when the draft could not be read, rather than offering to replace it", () => {
    hook.error = new Error("offline");
    shown(null);
    expect(screen.getByRole("alert")).toHaveTextContent("The drafted keys could not be read.");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("does not use keys listed from an answer edited since", () => {
    shown(draft("ready"), "Invoice INV-7", "Invoice INV-8");
    expect(screen.getByRole("button", { name: "Use these keys" })).toBeDisabled();
    expect(
      screen.getByText("Save the reference answer first: keys are listed from the saved one."),
    ).toBeInTheDocument();
  });

  it("says while the keys are listed", () => {
    shown(draft("running", []));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Listing the facts of the reference answer…",
    );
  });

  it("names what it found and uses it, dismissing the draft", async () => {
    const onUse = shown(draft("ready"));
    expect(
      screen.getByText("Found 7 keys: Fact 1, Fact 2, Fact 3, Fact 4, Fact 5 and 2 more."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use these keys" }));
    expect(onUse).toHaveBeenCalledWith(KEYS);
    expect(hook.dismiss).toHaveBeenCalled();
  });

  it("says when nothing was found, offering only to dismiss it", async () => {
    shown(draft("ready", []));
    expect(screen.getByText("The reference answer states no facts to check.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use these keys" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(hook.dismiss).toHaveBeenCalled();
  });

  it("says why the keys could not be listed, and offers to try again", async () => {
    shown(draft("failed", [], "over budget"));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The keys could not be listed: over budget",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(hook.start).toHaveBeenCalled();
  });

  it("names a failure without a reason, and waits while one is asked for", () => {
    hook.starting = true;
    shown(draft("failed", [], null));
    expect(screen.getByRole("alert")).toHaveTextContent("The keys could not be listed:");
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
  });
});
