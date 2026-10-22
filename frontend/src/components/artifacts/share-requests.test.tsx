import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactRequests } from "./artifact-requests";
import { DataChangeReview } from "./data-change-review";
import { RequestAccessScreen } from "./request-access-screen";
import { ApiError } from "@/lib/api-error";
import type {
  ArtifactDetail,
  ArtifactShareRequest,
  ArtifactVersionReview,
  BindingParts,
} from "@/types/artifact";

/**
 * A page's requests in the console: the screen a member who may not open it sees,
 * the list the Share dialog holds, and the panel that reviews a version's data change.
 */

const requestAccess = { mutate: vi.fn(), isPending: false, isSuccess: false };
const requestsMock = vi.fn();
const approve = { mutate: vi.fn(), isPending: false };
const decline = { mutate: vi.fn(), isPending: false };
const reviewMock = vi.fn();
vi.mock("@/hooks/use-artifact-requests", () => ({
  isConsentRequired: (error: unknown) =>
    error instanceof ApiError && error.code === "CONSENT_REQUIRED",
  useRequestAccess: () => requestAccess,
  useArtifactRequests: (...args: unknown[]) => requestsMock(...args),
  useArtifactRequestActions: () => ({ approve, decline }),
  useVersionReview: (...args: unknown[]) => reviewMock(...args),
}));

function request(overrides: Partial<ArtifactShareRequest> = {}): ArtifactShareRequest {
  return {
    id: "r1",
    artifact_id: "a1",
    kind: "access",
    status: "pending",
    requester_user_id: "u2",
    requester_name: "Bea Builder",
    version_id: null,
    version_number: null,
    query_fingerprint: null,
    requested_visibility: null,
    requested_subjects: [],
    note: null,
    void_reason: null,
    decided_by_user_id: null,
    decided_at: null,
    created_at: "2026-10-22T10:00:00Z",
    can_decide: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  requestAccess.isPending = false;
  requestAccess.isSuccess = false;
  approve.isPending = false;
  decline.isPending = false;
});

describe("RequestAccessScreen", () => {
  it("says only that there is no access, and offers a request with an optional note", async () => {
    const { container } = render(<RequestAccessScreen artifactId="a1" requested={false} />);

    expect(screen.getByText("You don't have access to this page")).toBeInTheDocument();
    // Nothing of the page: the screen holds its own words and no more.
    expect(container).not.toHaveTextContent("Weekly report");
    const note = screen.getByLabelText("Note for the owner (optional)");
    expect(note).toHaveAttribute("maxlength", "500");

    await userEvent.type(note, "  Need the Q3 numbers ");
    await userEvent.click(screen.getByRole("button", { name: "Request access" }));
    expect(requestAccess.mutate).toHaveBeenCalledWith("Need the Q3 numbers");
  });

  it("sends no note when none was written, and holds the button while sending", async () => {
    const { rerender } = render(<RequestAccessScreen artifactId="a1" requested={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Request access" }));
    expect(requestAccess.mutate).toHaveBeenCalledWith(null);

    requestAccess.isPending = true;
    rerender(<RequestAccessScreen artifactId="a1" requested={false} />);
    expect(screen.getByRole("button", { name: "Request access" })).toBeDisabled();
  });

  it.each([
    ["the server already holds a request", true, false],
    ["the request was just sent", false, true],
  ])("shows the requested state when %s", (_name, requested, sent) => {
    requestAccess.isSuccess = sent;
    render(<RequestAccessScreen artifactId="a1" requested={requested} />);

    expect(screen.getByText("Access requested")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request access" })).toBeNull();
  });
});

function page(overrides: Partial<ArtifactDetail> = {}): ArtifactDetail {
  return {
    id: "a1",
    can_edit: true,
    may_change_owner: false,
    may_grant_edit_data: false,
    consent: null,
    ...overrides,
  } as ArtifactDetail;
}

function listed(items: ArtifactShareRequest[], isLoading = false) {
  requestsMock.mockReturnValue({ requests: items, isLoading, error: null });
}

function renderRequests(artifact = page()) {
  const handlers = { onReview: vi.fn(), onConsentRequired: vi.fn() };
  render(<ArtifactRequests artifact={artifact} {...handlers} />);
  return handlers;
}

describe("ArtifactRequests", () => {
  it("words each kind by what it asks, with the requester and their note", () => {
    listed([
      request({ id: "r1", kind: "access", note: "Need the Q3 numbers" }),
      request({
        id: "r2",
        kind: "audience",
        requested_visibility: "org",
        requested_subjects: [
          {
            level: "edit",
            user_id: "u3",
            email: "cy@example.com",
            group_id: null,
            group_name: null,
          },
          { level: "use", user_id: null, email: null, group_id: "g1", group_name: "Sales" },
        ],
      }),
      request({ id: "r3", kind: "version", version_number: 4, requester_name: null }),
    ]);
    renderRequests();

    expect(screen.getByText("Bea Builder asked for access to this page")).toBeInTheDocument();
    expect(screen.getByText("Note: Need the Q3 numbers")).toBeInTheDocument();
    expect(
      screen.getByText("Bea Builder asked to share this page with more people"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Visible to the whole organization; cy@example.com - can edit; Sales - can use",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Someone changed what v4 reads")).toBeInTheDocument();
  });

  it("words a private or read-only ask too", () => {
    listed([
      request({
        kind: "audience",
        requested_visibility: "private",
        requested_subjects: [
          { level: "read", user_id: null, email: null, group_id: null, group_name: null },
        ],
      }),
    ]);
    renderRequests();

    expect(screen.getByText("Private; - can read")).toBeInTheDocument();
  });

  it("words an ask that names people only", () => {
    listed([
      request({
        kind: "audience",
        requested_subjects: [
          {
            level: "use",
            user_id: "u3",
            email: "cy@example.com",
            group_id: null,
            group_name: null,
          },
        ],
      }),
    ]);
    renderRequests();

    expect(screen.getByText("cy@example.com - can use")).toBeInTheDocument();
  });

  it("approves and declines what the server says the caller may decide", async () => {
    listed([request({ id: "r1" }), request({ id: "r2", can_decide: false })]);
    renderRequests();

    const rows = screen.getAllByRole("listitem");
    expect(within(rows[1] as HTMLElement).queryByRole("button")).toBeNull();
    await userEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: /^Decline/ }));
    expect(decline.mutate).toHaveBeenCalledWith("r1");
    await userEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: /^Approve/ }));
    expect(approve.mutate).toHaveBeenCalledWith("r1", expect.any(Object));
  });

  it("holds the buttons while a decision is in flight", () => {
    approve.isPending = true;
    listed([request()]);
    renderRequests();

    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Decline/ })).toBeDisabled();
  });

  it("tells the caller approving was refused for want of consent, and only that", async () => {
    listed([request()]);
    const { onConsentRequired } = renderRequests();
    await userEvent.click(screen.getByRole("button", { name: /^Approve/ }));
    const { onError } = approve.mutate.mock.calls[0]?.[1] as {
      onError: (error: unknown) => void;
    };

    onError(new ApiError(409, "x", { error: { code: "CONSENT_REQUIRED", message: "x" } }));
    expect(onConsentRequired).toHaveBeenCalledOnce();
    onError(new ApiError(409, "x", { error: { code: "CONCURRENT_CHANGE", message: "x" } }));
    expect(onConsentRequired).toHaveBeenCalledOnce();
  });

  it("offers a version request only Review and Decline, never a one-click Approve", async () => {
    listed([request({ kind: "version", version_id: "v4", version_number: 4 })]);
    renderRequests();

    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Review data change" })).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Decline the request from Bea Builder" }),
    );
    expect(decline.mutate).toHaveBeenCalledWith("r1");
  });

  it("names the requester on Approve and Decline", () => {
    listed([request()]);
    renderRequests();

    expect(
      screen.getByRole("button", { name: "Approve the request from Bea Builder" }),
    ).toBeVisible();
  });

  it("opens the review of a version request", async () => {
    const version = request({ kind: "version", version_id: "v4", version_number: 4 });
    listed([version]);
    const { onReview } = renderRequests();

    await userEvent.click(screen.getByRole("button", { name: "Review data change" }));
    expect(onReview).toHaveBeenCalledWith(version);
  });

  it("marks what was decided or voided, behind a toggle that asks for them", async () => {
    listed([
      request({ id: "r1", status: "approved", can_decide: false }),
      request({ id: "r2", status: "declined", can_decide: false }),
      request({ id: "r3", status: "voided", void_reason: "page_changed", can_decide: false }),
      request({ id: "r4", status: "voided", void_reason: "replaced", can_decide: false }),
      request({ id: "r5", status: "voided", void_reason: "owner_changed", can_decide: false }),
      request({ id: "r6", status: "voided", void_reason: "archived", can_decide: false }),
      request({ id: "r7", status: "voided", void_reason: "superseded", can_decide: false }),
      request({ id: "r8", status: "voided", void_reason: null, can_decide: false }),
    ]);
    renderRequests();

    expect(requestsMock).toHaveBeenLastCalledWith("a1", false, true);
    await userEvent.click(screen.getByRole("switch", { name: "Show decided" }));
    expect(requestsMock).toHaveBeenLastCalledWith("a1", true, true);
    for (const text of [
      "Approved",
      "Declined",
      "Void - the page's data changed",
      "Replaced by a newer request",
      "Void - the owner changed",
      "Void - the page was archived",
      "Superseded by a newer version",
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getAllByText("Void")).toHaveLength(1);
  });

  it("says there is nothing waiting to a decider, and draws nothing for a reader with none", () => {
    listed([]);
    const { unmount } = render(
      <ArtifactRequests artifact={page()} onReview={vi.fn()} onConsentRequired={vi.fn()} />,
    );
    expect(screen.getByText("No requests.")).toBeInTheDocument();
    unmount();

    const { container } = render(
      <ArtifactRequests
        artifact={page({ can_edit: false })}
        onReview={vi.fn()}
        onConsentRequired={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a reader their own request without a toggle", () => {
    listed([request({ can_decide: false })]);
    renderRequests(page({ can_edit: false }));

    expect(screen.getByText("Bea Builder asked for access to this page")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("says nothing while it loads", () => {
    listed([], true);
    renderRequests();

    expect(screen.queryByText("No requests.")).toBeNull();
  });
});

const QUERY: BindingParts = {
  table: "Deals",
  filters: [{ column: "Stage", op: "eq", value: "Won" }],
  sort: { record_time: null, column: "Amount", derived: null, direction: "desc" },
  limit: 50,
  fields: [{ name: "amount", column: "Amount", type: "number", derived: null }],
  linked: ["Accounts"],
};

function review(overrides: Partial<ArtifactVersionReview> = {}): ArtifactVersionReview {
  return {
    version: {
      id: "v4",
      number: 4,
      media_type: "text/html",
      size_bytes: 1,
      run_id: "run-9",
      restored_from: null,
      consent_state: "pending",
      created_at: "2026-10-22T10:00:00Z",
    },
    compared_to: 3,
    publisher_name: "Bea Builder",
    bindings: [],
    unchanged: [],
    widens: false,
    problem: null,
    ...overrides,
  };
}

function reviewing(data: ArtifactVersionReview | undefined, isLoading = false) {
  reviewMock.mockReturnValue({ data, isLoading });
}

function renderReview(props: Partial<React.ComponentProps<typeof DataChangeReview>> = {}) {
  const handlers = {
    onAudienceShown: vi.fn(),
    audienceAvailable: () => true,
    onApprove: vi.fn().mockResolvedValue(undefined),
    onDecline: vi.fn(),
    onClose: vi.fn(),
  };
  render(
    <DataChangeReview
      artifactId="a1"
      versionId="v4"
      fingerprint={"f".repeat(64)}
      audienceShown={false}
      pending={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("DataChangeReview", () => {
  it("marks each binding by what it does to what the audience reads", () => {
    reviewing(
      review({
        widens: true,
        unchanged: ["summary", "totals"],
        bindings: [
          {
            name: "deals",
            change: "added",
            effect: "widens",
            parts: QUERY,
            changes: [],
          },
          {
            name: "old",
            change: "removed",
            effect: "narrows",
            parts: { ...QUERY, table: "Leads" },
            changes: [],
          },
          {
            name: "people",
            change: "changed",
            effect: "widens",
            parts: null,
            changes: [
              { aspect: "table", change: "changed", effect: "widens", before: "A", after: "B" },
              {
                aspect: "field",
                change: "added",
                effect: "widens",
                before: null,
                after: { name: "pay", column: "Salary", type: "number", derived: null },
              },
              {
                aspect: "field",
                change: "removed",
                effect: "narrows",
                before: {
                  name: "band",
                  column: "Level",
                  type: "text",
                  derived: {
                    kind: "formula",
                    inputs: ["Level"],
                    table: null,
                    column: null,
                    aggregate: null,
                  },
                },
                after: null,
              },
              {
                aspect: "field",
                change: "changed",
                effect: "widens",
                before: { name: "n", column: "Name", type: "text", derived: null },
                after: { name: "n", column: "Email", type: "text", derived: null },
              },
              {
                aspect: "filter",
                change: "removed",
                effect: "widens",
                before: { column: "Stage", op: "eq", value: "Won" },
                after: null,
              },
              {
                aspect: "filter",
                change: "added",
                effect: "narrows",
                before: null,
                after: { column: "Region", op: "in", value: ["EU", "US"] },
              },
              {
                aspect: "filter",
                change: "changed",
                effect: "widens",
                before: { column: "Stage", op: "is_null", value: true },
                after: { column: "Stage", op: "is_null", value: false },
              },
              {
                aspect: "sort",
                change: "changed",
                effect: "widens",
                before: { record_time: null, column: "Amount", derived: null, direction: "asc" },
                after: {
                  record_time: "updated_at",
                  column: null,
                  derived: null,
                  direction: "desc",
                },
              },
              { aspect: "limit", change: "changed", effect: "widens", before: 10, after: 500 },
              {
                aspect: "linked",
                change: "added",
                effect: "widens",
                before: null,
                after: "Accounts",
              },
              {
                aspect: "linked",
                change: "removed",
                effect: "narrows",
                before: "Leads",
                after: null,
              },
              { aspect: "reach", change: "added", effect: "widens", before: null, after: "Salary" },
              {
                aspect: "reach",
                change: "removed",
                effect: "neutral",
                before: "Notes",
                after: null,
              },
            ],
          },
          { name: "calm", change: "changed", effect: "neutral", parts: null, changes: [] },
        ],
      }),
    );
    renderReview();

    expect(screen.getByRole("heading", { name: "Review the data change in v4" })).toBeVisible();
    // A new binding comes whole, as the Confirm data dialog words it.
    expect(screen.getByText("deals - new")).toBeVisible();
    expect(screen.getByText("deals reads Deals")).toBeVisible();
    expect(screen.getByText('Only records where Stage is "Won".')).toBeVisible();
    expect(screen.getByText("amount: Amount (Number)")).toBeVisible();
    expect(screen.getByText("Also reads, through links: Accounts")).toBeVisible();
    expect(screen.getByText("old - removed")).toBeVisible();
    expect(screen.getByText("It no longer reads Leads.")).toBeVisible();

    const widening = screen.getByText("Table: A -> B").closest("li");
    expect(widening).toHaveClass("bg-warning/10");
    expect(within(widening as HTMLElement).getByText("Reads more")).toBeVisible();
    expect(screen.getByText("Field added: pay: Salary (Number)")).toBeVisible();
    expect(screen.getByText("Field removed: band: Level: formula over Level")).toBeVisible();
    expect(screen.getByText("Field changed: n: Name (Text) -> n: Email (Text)")).toBeVisible();
    expect(screen.getByText('Condition dropped: Stage is "Won"')).toBeVisible();
    expect(screen.getByText('Condition added: Region is one of "EU", "US"')).toBeVisible();
    expect(
      screen.getByText("Condition changed: Stage is empty -> Stage is not empty"),
    ).toBeVisible();
    expect(
      screen.getByText("Order: Amount, ascending -> when last changed, descending"),
    ).toBeVisible();
    expect(screen.getByText("Limit: 10 -> 500")).toBeVisible();
    expect(screen.getByText("Now also reads, through links: Accounts")).toBeVisible();
    expect(screen.getByText("No longer reads, through links: Leads")).toBeVisible();
    expect(screen.getByText("Now also reads, in a condition or the order: Salary")).toBeVisible();
    expect(screen.getByText("No longer reads: Notes")).toBeVisible();
    // A narrowing is marked plainly, and a binding that reads the same is folded away.
    const narrowing = screen
      .getByText("Field removed: band: Level: formula over Level")
      .closest("li");
    expect(narrowing).not.toHaveClass("bg-warning/10");
    expect(screen.getAllByText("Reads less").length).toBeGreaterThan(0);
    expect(screen.getByText("2 unchanged bindings")).toBeVisible();
    expect(screen.getByText("summary, totals")).not.toBeVisible();
  });

  it("names the publisher, when and the conversation, and says what it is compared with", () => {
    reviewing(review());
    renderReview();

    expect(screen.getByText(/Published by Bea Builder on /)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the conversation" })).toHaveAttribute(
      "href",
      "/runs?run=run-9",
    );
    expect(screen.getByText("Compared with v3, which the audience sees now.")).toBeVisible();
    expect(screen.getByText("It reads the same data as the audience's version.")).toBeVisible();
  });

  it("has no conversation link when the run is gone, and no audience toggle when it sees nothing", () => {
    reviewing(
      review({
        compared_to: null,
        publisher_name: null,
        version: { ...review().version, run_id: null },
      }),
    );
    renderReview();

    expect(screen.queryByRole("link", { name: "Open the conversation" })).toBeNull();
    expect(screen.queryByRole("switch", { name: "Audience sees now" })).toBeNull();
    expect(screen.getByText("The audience sees no version of this page yet.")).toBeVisible();
  });

  it("switches the frame to what the audience sees now, and back", async () => {
    reviewing(review());
    const { onAudienceShown } = renderReview();

    await userEvent.click(screen.getByRole("switch", { name: "Audience sees now" }));
    expect(onAudienceShown).toHaveBeenCalledWith(true, 3);
  });

  it("shows the problem the server found, and holds approval until it has loaded", () => {
    reviewing(review({ problem: "A table in it can't be read." }));
    renderReview();
    expect(screen.getByText("A table in it can't be read.")).toBeVisible();
  });

  it("is a skeleton while it loads, and an error when it could not", () => {
    reviewing(undefined, true);
    const { unmount } = render(
      <DataChangeReview
        artifactId="a1"
        versionId="v4"
        fingerprint="f"
        audienceShown={false}
        onAudienceShown={vi.fn()}
        audienceAvailable={() => true}
        onApprove={vi.fn()}
        onDecline={vi.fn()}
        onClose={vi.fn()}
        pending={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    unmount();

    reviewing(undefined);
    renderReview();
    expect(screen.getByText("Couldn't load the data change.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("approves with the fingerprint the request was made against, then closes", async () => {
    reviewing(review());
    const { onApprove, onClose } = renderReview();

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(onApprove).toHaveBeenCalledWith("f".repeat(64));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("shows a refused approval and stays open", async () => {
    reviewing(review());
    const { onApprove, onClose } = renderReview();
    onApprove.mockRejectedValue(new ApiError(403, "Only the owner may confirm."));

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("Only the owner may confirm.")).toBeVisible();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes without a message of its own when approving is refused as stale (409)", async () => {
    reviewing(review());
    const { onApprove, onClose } = renderReview();
    onApprove.mockRejectedValue(new ApiError(409, "A newer version landed."));

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(screen.queryByText("A newer version landed.")).toBeNull();
  });

  it("disables the audience toggle, and says why, when that version is no longer listed", () => {
    reviewing(review());
    renderReview({ audienceAvailable: () => false });

    expect(screen.getByRole("switch", { name: "Audience sees now" })).toBeDisabled();
    expect(screen.getByText(/no longer listed/)).toBeVisible();
  });

  it("declines, and holds both buttons while it works; Approve needs a fingerprint", async () => {
    reviewing(review());
    const { onDecline } = renderReview();
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(onDecline).toHaveBeenCalledOnce();
  });

  it("holds the buttons while pending and without a fingerprint", () => {
    reviewing(review());
    renderReview({ pending: true, fingerprint: null });

    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Decline" })).toBeDisabled();
  });

  it("closes from its own button", async () => {
    reviewing(review());
    const { onClose } = renderReview();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("has a title before the version is known", () => {
    reviewing(undefined, true);
    renderReview();
    expect(screen.getByRole("heading", { name: "Review data change" })).toBeVisible();
  });
});
