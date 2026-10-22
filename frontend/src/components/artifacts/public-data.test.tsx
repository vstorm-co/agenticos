import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicDataControl, PublicDataNotice } from "./public-data-control";
import { ApiError } from "@/lib/api-error";
import type {
  ArtifactConsent,
  ArtifactDetail,
  ArtifactDisclosure,
  ArtifactPublicData,
  ArtifactPublicDataDisclosure,
} from "@/types/artifact";

/**
 * A page's data on its public link (#1975): where it stands in the share dialog
 * for each state the server reports, the dialog that shows the data and the whole
 * audience before confirming, and the strip line for an editor when a query change
 * blanked the public page.
 */

const disclosureMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  usePublicDataDisclosure: (...args: unknown[]) => disclosureMock(...args),
}));

const FP = "f".repeat(64);
const DIGEST = "d".repeat(64);

function consent(overrides: Partial<ArtifactConsent> = {}): ArtifactConsent {
  return {
    version: 3,
    state: "consented",
    fingerprint: FP,
    automatic: false,
    grown: [],
    via: null,
    audience_version: 3,
    shared: true,
    owner_name: "Olga Owner",
    withdrawn_at: null,
    auto_consent: false,
    may_confirm: false,
    may_withdraw: false,
    may_enable_auto_consent: false,
    may_disable_auto_consent: false,
    ...overrides,
  };
}

function publicData(overrides: Partial<ArtifactPublicData> = {}): ArtifactPublicData {
  return {
    switch_on: true,
    consented: false,
    fingerprint: null,
    version: 3,
    by_name: null,
    at: null,
    holds: false,
    not_holding: null,
    ...overrides,
  };
}

function artifact(overrides: Partial<ArtifactDetail> = {}): ArtifactDetail {
  return {
    id: "a1",
    name: "report",
    title: "Report",
    visibility: "org",
    owner_user_id: "u1",
    agent_id: "ag1",
    environment_id: null,
    environment_name: null,
    public_url: "https://x.example/p/key",
    published_at: "2026-09-22T10:00:00Z",
    archived_at: null,
    current_version: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: null,
    can_edit: true,
    may_change_owner: false,
    may_grant_edit_data: false,
    may_confirm_public_data: true,
    public_data: publicData(),
    live: true,
    bindings: [{ name: "deals", table_id: "t1", fields: ["stage"] }],
    consent: consent(),
    public_link: {
      expires_at: null,
      pinned_version_id: null,
      pinned_version: null,
      password_protected: false,
      view_count: 0,
      last_viewed_at: null,
      embed_origins: [],
      embed_url: null,
    },
    ...overrides,
  };
}

const DATA: ArtifactDisclosure = {
  version: 3,
  fingerprint: FP,
  bindings: {},
  parts: {
    deals: {
      table: "Deals",
      filters: [],
      sort: { record_time: null, column: "Amount", derived: null, direction: "desc" },
      limit: 50,
      fields: [{ name: "stage", column: "Stage", type: "text", derived: null }],
      linked: [],
    },
  },
  tables: ["Deals"],
  visibility: "org",
  people: [],
  groups: [],
  roles: ["owner"],
  problem: null,
};

function shown(
  overrides: Partial<ArtifactPublicDataDisclosure> = {},
): ArtifactPublicDataDisclosure {
  return {
    switch_on: true,
    link_on: true,
    password_protected: false,
    expires_at: null,
    embed_origins: [],
    version: 3,
    fingerprint: FP,
    audience_digest: DIGEST,
    member_consent: true,
    data: DATA,
    confirmable: true,
    problem: null,
    ...overrides,
  };
}

function control(value: ArtifactDetail) {
  const handlers = {
    onConfirm: vi.fn().mockResolvedValue(undefined),
    onWithdraw: vi.fn(),
  };
  const view = render(
    <PublicDataControl
      artifact={value}
      onConfirm={handlers.onConfirm}
      confirmPending={false}
      onWithdraw={handlers.onWithdraw}
      withdrawPending={false}
    />,
  );
  return { ...handlers, ...view };
}

const refetch = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  disclosureMock.mockReturnValue({ data: shown(), isLoading: false, refetch });
});

describe("the live data control on a public link", () => {
  it.each([
    ["has no table data", { bindings: [] }],
    ["has no public link", { public_url: null }],
    ["is seen by somebody who may not edit it", { public_data: null }],
  ])("is not drawn for a page that %s", (_name, overrides) => {
    const { container } = control(artifact(overrides));

    expect(container).toBeEmptyDOMElement();
  });

  it("says an admin has to turn the organization's switch on, and offers nothing", () => {
    control(artifact({ public_data: publicData({ switch_on: false }) }));

    expect(screen.getByTestId("public-data-control")).toHaveTextContent(
      "Live data on this public link",
    );
    expect(screen.getByText(/An Owner or Admin has to turn it on/)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers Confirm to whoever may confirm for a page that is not", async () => {
    control(artifact());

    expect(screen.getByText(/Confirm to show the table records/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Confirm data for the public link");
  });

  it("tells an editor who may not confirm that the owner can enable it", () => {
    control(artifact({ may_confirm_public_data: false }));

    expect(screen.getByText(/The page's owner, or an Owner or Admin, can enable it/)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says what is shown while it holds, and withdraws after asking", async () => {
    const { onWithdraw } = control(
      artifact({
        public_data: publicData({
          consented: true,
          holds: true,
          fingerprint: FP,
          by_name: "Olga Owner",
          at: "2026-10-01T10:00:00Z",
        }),
      }),
    );

    expect(
      screen.getByText(/Shown on the public link: version 3, confirmed by Olga Owner/),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Confirm again" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("keep showing the page, without its data");
    await userEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));

    expect(onWithdraw).toHaveBeenCalledOnce();
    onWithdraw.mock.calls[0]?.[0]();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("copes with a confirmation that names no time", () => {
    control(
      artifact({
        public_data: publicData({ consented: true, holds: true, fingerprint: FP, version: null }),
      }),
    );

    expect(screen.getByText(/Shown on the public link: version 0/)).toBeVisible();
  });

  it.each([
    ["switch_off", "an Owner or Admin switched live data on public pages off", false],
    ["no_served_version", "the public link serves no version of this page now", false],
    ["queries_changed", "the page's queries changed", true],
    ["owner_gone", "the page's owner is no longer an active member", false],
    ["owner_membership_changed", "the page's owner changed since the data was confirmed", false],
    ["member_consent_missing", "consent for members to read this version's data is missing", false],
    ["link_expired", "the public link has expired", false],
  ] as const)("says why a confirmed link shows no data: %s", async (reason, words, again) => {
    control(
      artifact({
        public_data: publicData({
          consented: true,
          holds: false,
          fingerprint: FP,
          not_holding: reason,
        }),
      }),
    );

    expect(screen.getByTestId("public-data-control")).toHaveTextContent(words);
    expect(screen.queryByRole("button", { name: "Confirm again" }) !== null).toBe(again);
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeVisible();
  });

  it("keeps the control and Withdraw while data is consented though the latest version has no bindings", () => {
    control(
      artifact({
        bindings: [],
        public_data: publicData({
          consented: true,
          fingerprint: FP,
          not_holding: "queries_changed",
        }),
      }),
    );

    expect(screen.getByRole("button", { name: "Withdraw" })).toBeVisible();
  });

  it("draws no control for a page with no bindings and nothing consented", () => {
    const { container } = control(artifact({ bindings: [] }));

    expect(container).toBeEmptyDOMElement();
  });

  it("offers no Withdraw to somebody who may not edit", () => {
    control(
      artifact({
        can_edit: false,
        public_data: publicData({
          consented: true,
          fingerprint: FP,
          not_holding: "switch_off",
        }),
      }),
    );

    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
  });

  it("offers no Confirm again to somebody who may not confirm", () => {
    control(
      artifact({
        may_confirm_public_data: false,
        public_data: publicData({
          consented: true,
          fingerprint: FP,
          not_holding: "queries_changed",
        }),
      }),
    );

    expect(screen.queryByRole("button", { name: "Confirm again" })).toBeNull();
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeVisible();
  });
});

describe("the dialog that confirms the data for the public link", () => {
  async function open(value = artifact()) {
    const view = control(value);
    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));
    return { ...view, dialog: await screen.findByRole("dialog") };
  }

  it("shows the queries and every fact about who reaches the link", async () => {
    disclosureMock.mockReturnValue({
      data: shown({
        password_protected: true,
        expires_at: "2026-12-24T12:00:00Z",
        embed_origins: ["https://a.example", "https://b.example"],
      }),
      isLoading: false,
      refetch,
    });
    const { dialog } = await open();

    expect(disclosureMock).toHaveBeenCalledWith("a1", true);
    for (const words of [
      "deals reads Deals",
      "Tables read: Deals",
      "Anyone with the public link - no account, no sign-in.",
      "They have to enter the link's password.",
      "The link stops working after Dec 24, 2026.",
      "https://a.example, https://b.example",
    ]) {
      expect(dialog).toHaveTextContent(words);
    }
    expect(dialog).not.toHaveTextContent("Everyone in the organization");
  });

  it("says when there is no password, no expiry and no embedding site", async () => {
    const { dialog } = await open();

    expect(dialog).toHaveTextContent("No password: the link alone opens it.");
    expect(dialog).toHaveTextContent("The link does not expire.");
    expect(dialog).not.toHaveTextContent("embed the page");
  });

  it("sends exactly the digests it showed, then closes", async () => {
    const { dialog, onConfirm } = await open();

    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));

    expect(onConfirm).toHaveBeenCalledWith(FP, DIGEST);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes on a 409 so the person looks at the page as it is now", async () => {
    const { dialog, onConfirm } = await open();
    onConfirm.mockRejectedValue(new ApiError(409, "changed"));

    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(refetch).not.toHaveBeenCalled();
  });

  it("shows another refusal, reads the disclosure again and holds the button", async () => {
    const { dialog, onConfirm } = await open();
    onConfirm.mockRejectedValue(new ApiError(403, "Not for you"));

    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));

    expect(await within(dialog).findByText("Not for you")).toBeVisible();
    expect(refetch).toHaveBeenCalledOnce();
    expect(within(dialog).getByRole("button", { name: "Confirm data" })).toBeDisabled();
  });

  it("clears a refusal when it is closed with Cancel or Escape", async () => {
    const { dialog, onConfirm } = await open();
    onConfirm.mockRejectedValue(new ApiError(403, "Not for you"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm data" }));
    await within(dialog).findByText("Not for you");

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));
    const again = await screen.findByRole("dialog");
    expect(within(again).queryByText("Not for you")).toBeNull();
    await userEvent.click(within(again).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it.each([
    [
      "the switch is off",
      { switch_on: false, confirmable: false },
      "turn on live data on public pages",
    ],
    ["the link is off", { link_on: false, confirmable: false }, "The page has no public link"],
    [
      "the server gives a reason",
      { member_consent: false, confirmable: false, problem: "The owner hasn't confirmed it." },
      "The owner hasn't confirmed it.",
    ],
    [
      "the page queries carry the reason",
      { confirmable: false, data: { ...DATA, problem: "The owner can't read a table." } },
      "The owner can't read a table.",
    ],
  ])("holds the button when %s, and says why", async (_name, overrides, words) => {
    disclosureMock.mockReturnValue({ data: shown(overrides), isLoading: false, refetch });
    const { dialog } = await open();

    expect(dialog).toHaveTextContent(words);
    expect(within(dialog).getByRole("button", { name: "Confirm data" })).toBeDisabled();
  });

  it("holds the button for a page with nothing to fingerprint", async () => {
    disclosureMock.mockReturnValue({
      data: shown({ fingerprint: null, data: null, confirmable: false }),
      isLoading: false,
      refetch,
    });
    const { dialog } = await open();

    expect(within(dialog).getByRole("button", { name: "Confirm data" })).toBeDisabled();
    expect(dialog).not.toHaveTextContent("Tables read");
  });

  it("shows a loading state, then an error when the disclosure cannot be read", async () => {
    disclosureMock.mockReturnValue({ data: undefined, isLoading: true, refetch });
    const { dialog, unmount } = await open();
    expect(within(dialog).getByRole("button", { name: "Confirm data" })).toBeDisabled();
    unmount();

    disclosureMock.mockReturnValue({ data: undefined, isLoading: false, refetch });
    await open();
    expect(await screen.findByText("Could not load what would be shared")).toBeVisible();
  });
});

describe("the strip line for an editor", () => {
  function strip(value: ArtifactDetail) {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const view = render(
      <PublicDataNotice artifact={value} onConfirm={onConfirm} confirmPending={false} />,
    );
    return { onConfirm, ...view };
  }
  const moved = (overrides: Partial<ArtifactDetail> = {}) =>
    artifact({
      public_data: publicData({ consented: true, fingerprint: FP, not_holding: "queries_changed" }),
      ...overrides,
    });

  it("says the public page shows no data until it is confirmed again, and confirms from there", async () => {
    const { onConfirm } = strip(moved());

    expect(screen.getByRole("status")).toHaveTextContent(
      "This page's queries changed, so its public link shows no data until it is confirmed again.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm data" }),
    );
    expect(onConfirm).toHaveBeenCalledWith(FP, DIGEST);
  });

  it("tells an editor who may not confirm, without a button", () => {
    strip(moved({ may_confirm_public_data: false }));

    expect(screen.getByRole("status")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([
    ["no public data state", { public_data: null }],
    ["a page that was never confirmed", { public_data: publicData() }],
    [
      "one that still holds",
      { public_data: publicData({ consented: true, holds: true, fingerprint: FP }) },
    ],
    [
      "the switch being off",
      {
        public_data: publicData({
          consented: true,
          switch_on: false,
          fingerprint: FP,
          not_holding: "switch_off",
        }),
      },
    ],
  ])("draws nothing for %s", (_name, overrides) => {
    const { container } = strip(artifact(overrides));

    expect(container).toBeEmptyDOMElement();
  });
});
