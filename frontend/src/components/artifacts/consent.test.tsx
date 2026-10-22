import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTO_CONSENT_WORDING, AutoConsentSetting } from "./auto-consent-setting";
import { ConfirmDataDialog } from "./confirm-data-dialog";
import { ConsentNotice } from "./consent-notice";
import { pinnable } from "./public-link-settings";
import { ApiError } from "@/lib/api-error";
import type { ArtifactConsent, ArtifactDisclosure, ArtifactVersion } from "@/types/artifact";

/**
 * A page's consent in the console: the strip line each caller served the latest
 * version reads, the Confirm data dialog with what it shares and with whom, and
 * the auto-consent switch. Every control here is drawn from the server's
 * `may_*` answers, so each test asserts what is drawn for which answer.
 */

const disclosureMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactDisclosure: (...args: unknown[]) => disclosureMock(...args),
}));

function consent(overrides: Partial<ArtifactConsent> = {}): ArtifactConsent {
  return {
    version: 3,
    state: "pending",
    fingerprint: "f".repeat(64),
    automatic: false,
    grown: [],
    via: null,
    audience_version: 2,
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

function notice(value: ArtifactConsent, isOwner = false) {
  const handlers = { onConfirm: vi.fn(), onWithdraw: vi.fn() };
  const { container } = render(<ConsentNotice consent={value} isOwner={isOwner} {...handlers} />);
  return { ...handlers, container };
}

describe("ConsentNotice", () => {
  it("asks the owner to confirm, saying what the audience still sees", async () => {
    const { onConfirm } = notice(consent({ may_confirm: true }), true);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Nobody has confirmed sharing the data v3 reads yet. The audience still sees v2 until you confirm.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("tells an editor who confirms, and offers Withdraw while the audience reads data", async () => {
    const { onWithdraw } = notice(consent({ may_withdraw: true }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "The audience still sees v2 until Olga Owner confirms.",
    );
    expect(screen.queryByRole("button", { name: "Confirm data" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Stop sharing data" }));
    expect(onWithdraw).toHaveBeenCalledOnce();
  });

  it("offers no Withdraw when the audience reads no data", () => {
    notice(consent({ may_withdraw: true, shared: false }));

    expect(screen.queryByRole("button", { name: "Stop sharing data" })).toBeNull();
  });

  it("says who opens a page nothing of which is the audience's yet", () => {
    notice(consent({ audience_version: null, owner_name: null }));

    expect(screen.getByRole("status")).toHaveTextContent(
      "Only its owner, its editors and the roles that open every page can open it until its owner confirms its data.",
    );
  });

  it("says a withdrawal is what the data waits on", () => {
    notice(consent({ state: "withdrawn", may_confirm: true }));

    expect(screen.getByRole("status")).toHaveTextContent("Sharing this page's data was withdrawn.");
    expect(screen.getByRole("button", { name: "Confirm data" })).toBeVisible();
  });

  it("tells whoever may confirm what an automatic consent added", () => {
    notice(
      consent({
        state: "consented",
        automatic: true,
        grown: ["+Deals", "+Salary"],
        may_confirm: true,
      }),
      true,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "v3 was consented automatically and reads more: +Deals, +Salary",
    );
  });

  it("says whose grant it was when an editor's republish was consented through one", () => {
    notice(
      consent({
        state: "consented",
        automatic: true,
        grown: ["+Deals"],
        via: "Bea Builder",
        may_confirm: true,
      }),
      true,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "v3 was consented automatically via Bea Builder's grant and reads more: +Deals",
    );
  });

  it.each([
    ["a confirmed consent", { state: "consented" as const }],
    ["an automatic one that added nothing", { state: "consented" as const, automatic: true }],
    [
      "an automatic one, to an editor",
      { state: "consented" as const, automatic: true, grown: ["+Deals"] },
    ],
  ])("draws nothing for %s", (_name, overrides) => {
    const { container } = notice(consent(overrides));

    expect(container).toBeEmptyDOMElement();
  });
});

const DISCLOSURE: ArtifactDisclosure = {
  version: 3,
  fingerprint: "a".repeat(64),
  bindings: {
    deals: {
      table: "Deals",
      filters: ["Stage is Won"],
      sort: "Amount, largest first",
      limit: 50,
      fields: { band: "Pay band: formula over Salary, Level" },
    },
    all: {
      table: "Customers",
      filters: [],
      sort: "Name",
      limit: 1,
      fields: { name: "Name (text)" },
    },
  },
  parts: {
    deals: {
      table: "Deals",
      filters: [
        { column: "Stage", op: "eq", value: "Won" },
        { column: "Region", op: "in", value: ["EU", "US"] },
        { column: "Closed", op: "is_null", value: true },
        { column: "Owner", op: "is_null", value: false },
      ],
      sort: { record_time: null, column: "Amount", derived: null, direction: "desc" },
      limit: 50,
      fields: [
        { name: "stage", column: "Stage", type: "single_select", derived: null },
        {
          name: "band",
          column: "Pay band",
          type: "formula",
          derived: {
            kind: "formula",
            inputs: ["Salary", "Level"],
            table: null,
            column: null,
            aggregate: null,
          },
        },
        {
          name: "plain",
          column: "Plain",
          type: "formula",
          derived: { kind: "formula", inputs: [], table: null, column: null, aggregate: null },
        },
        {
          name: "customer",
          column: "Customer",
          type: "link",
          derived: {
            kind: "link",
            inputs: [],
            table: "Customers",
            column: "Name",
            aggregate: null,
          },
        },
        {
          name: "ids",
          column: "Other",
          type: "link",
          derived: { kind: "link", inputs: [], table: "Staff", column: null, aggregate: null },
        },
        {
          name: "region",
          column: "Region",
          type: "lookup",
          derived: {
            kind: "lookup",
            inputs: [],
            table: "Customers",
            column: "Region",
            aggregate: null,
          },
        },
        {
          name: "total",
          column: "Total",
          type: "rollup",
          derived: {
            kind: "rollup",
            inputs: [],
            table: "Customers",
            column: "Spend",
            aggregate: "sum",
          },
        },
        {
          name: "n",
          column: "Count",
          type: "rollup",
          derived: {
            kind: "rollup",
            inputs: [],
            table: "Customers",
            column: null,
            aggregate: "count",
          },
        },
      ],
      linked: ["Customers", "Staff"],
    },
    all: {
      table: "Customers",
      filters: [],
      sort: { record_time: "updated_at", column: null, derived: null, direction: "asc" },
      limit: 1,
      fields: [{ name: "name", column: "Name", type: "text", derived: null }],
      linked: [],
    },
  },
  tables: ["Customers", "Deals", "Staff"],
  visibility: "org",
  people: ["ann@example.com"],
  groups: ["Sales"],
  roles: ["owner", "admin", "builder", "operator"],
  problem: null,
};

function dialog(onConfirm = vi.fn().mockResolvedValue(undefined)) {
  const onOpenChange = vi.fn();
  render(
    <ConfirmDataDialog
      artifactId="a1"
      versionId="v3"
      open
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
      loading={false}
    />,
  );
  return { onConfirm, onOpenChange };
}

describe("ConfirmDataDialog", () => {
  const refetch = vi.fn();
  beforeEach(() => {
    refetch.mockReset();
    disclosureMock.mockReturnValue({ data: DISCLOSURE, isLoading: false, refetch });
  });

  it("discloses the queries, the tables and everyone who reads them", () => {
    dialog();

    const body = screen.getByRole("dialog");
    expect(disclosureMock).toHaveBeenCalledWith("a1", "v3", true);
    for (const words of [
      "Confirm the data v3 shares",
      "deals reads Deals",
      'Only records where Stage is "Won"; Region is one of "EU", "US"; Closed is empty; Owner is not empty.',
      "Order: Amount, descending. At most 50 records.",
      "stage: Stage (Single select)",
      "band: Pay band: formula over Salary, Level",
      "plain: Plain: formula",
      "customer: Customer: link, labels from Customers -> Name",
      "ids: Other: link, labels from Staff -> record ids",
      "region: Region: lookup of Customers -> Region",
      "total: Total: rollup sum of Customers -> Spend",
      "n: Count: rollup count of Customers",
      "Also reads, through links: Customers, Staff",
      "Every record - no filter.",
      "Order: when last changed, ascending. At most 1 record.",
      "name: Name (Text)",
      "Tables read: Customers, Deals, Staff",
      "Everyone with one of these roles, which open every page: Owner, Admin, Builder, Operator",
      "Everyone in the organization",
      "Shared with: ann@example.com",
      "Shared with these groups, including whoever joins them: Sales",
    ]) {
      expect(body).toHaveTextContent(words);
    }
  });

  it("words an order by a worked-out column and a read the table no longer shows", () => {
    const base = DISCLOSURE.parts.all;
    disclosureMock.mockReturnValue({
      data: {
        ...DISCLOSURE,
        parts: {
          all: {
            ...base,
            sort: {
              record_time: null,
              column: "Pay band",
              derived: {
                kind: "formula",
                inputs: ["Salary"],
                table: null,
                column: null,
                aggregate: null,
              },
              direction: "desc",
            },
            fields: [
              {
                name: "gone",
                column: "Gone",
                type: "lookup",
                derived: {
                  kind: "lookup",
                  inputs: [],
                  table: "Staff",
                  column: null,
                  aggregate: null,
                },
              },
              {
                name: "odd",
                column: "Odd",
                type: "rollup",
                derived: {
                  kind: "rollup",
                  inputs: [],
                  table: "Staff",
                  column: "Pay",
                  aggregate: null,
                },
              },
            ],
          },
        },
      },
      isLoading: false,
      refetch,
    });
    dialog();

    const body = screen.getByRole("dialog");
    expect(body).toHaveTextContent("Order: Pay band (formula over Salary), descending.");
    expect(body).toHaveTextContent("gone: Gone: lookup of Staff -> ?");
    expect(body).toHaveTextContent("odd: Odd: rollup count of Staff -> Pay");
  });

  it("sends the fingerprint of what was shown, and closes", async () => {
    const { onConfirm, onOpenChange } = dialog();

    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));

    expect(onConfirm).toHaveBeenCalledWith("a".repeat(64));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("shows a refusal, reads the disclosure again and holds Confirm", async () => {
    const refused = new ApiError(403, "Only the owner can confirm this.");
    const { onOpenChange } = dialog(vi.fn().mockRejectedValue(refused));

    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Only the owner");
    expect(refetch).toHaveBeenCalledOnce();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByRole("button", { name: "Confirm data" })).toBeDisabled();
  });

  it("closes on a 409 - a newer version landed - instead of holding the stale one", async () => {
    const refused = new ApiError(409, "The page changed after you looked at it.");
    const { onOpenChange } = dialog(vi.fn().mockRejectedValue(refused));

    await userEvent.click(screen.getByRole("button", { name: "Confirm data" }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("holds Confirm when the owner can't share the data, saying why", () => {
    disclosureMock.mockReturnValue({
      data: { ...DISCLOSURE, problem: "The page's owner can't read 1 of the tables." },
      isLoading: false,
      refetch,
    });
    dialog();

    expect(screen.getByRole("alert")).toHaveTextContent("can't read 1 of the tables");
    expect(screen.getByRole("button", { name: "Confirm data" })).toBeDisabled();
  });

  it("holds Confirm while the disclosure is read", () => {
    disclosureMock.mockReturnValue({ data: undefined, isLoading: true, refetch });
    dialog();

    expect(screen.getByRole("button", { name: "Confirm data" })).toBeDisabled();
    expect(
      screen.getByRole("heading", { name: "Confirm the data this version shares" }),
    ).toBeVisible();
    expect(screen.queryByText("Couldn't load what this version shares.")).toBeNull();
  });

  it("closes on Cancel and on Escape, confirming nothing", async () => {
    const { onConfirm, onOpenChange } = dialog();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenNthCalledWith(1, false);
    expect(onOpenChange).toHaveBeenNthCalledWith(2, false);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("says so when the disclosure could not be read, and confirms nothing", () => {
    disclosureMock.mockReturnValue({ data: undefined, isLoading: false, refetch });
    dialog();

    expect(screen.getByText("Couldn't load what this version shares.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Confirm data" })).toBeDisabled();
  });
});

function setting(value: ArtifactConsent) {
  // The server takes the change: what the caller does once it has.
  const onChange = vi.fn((_changes: unknown, onDone?: () => void) => onDone?.());
  const { container } = render(
    <AutoConsentSetting consent={value} onChange={onChange} saving={false} />,
  );
  return { onChange, container };
}

describe("AutoConsentSetting", () => {
  it("turns on for the owner only after the popup saying what it does", async () => {
    const { onChange } = setting(consent({ may_enable_auto_consent: true }));

    await userEvent.click(
      screen.getByRole("switch", { name: "Don't ask for consent on republish" }),
    );
    const popup = screen.getByRole("dialog");
    expect(popup).toHaveTextContent(
      "Any change your runs make to this page's data, new columns and tables included, reaches everyone who can open it without asking you - API runs too.",
    );
    expect(popup).not.toHaveTextContent(/scheduled/i);
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));

    expect(onChange).toHaveBeenCalledWith(
      { enabled: true, confirmed: AUTO_CONSENT_WORDING },
      expect.any(Function),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("stays off when the owner cancels the popup", async () => {
    const { onChange } = setting(consent({ may_enable_auto_consent: true }));

    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("turns off at once for an admin", async () => {
    const { onChange } = setting(consent({ auto_consent: true, may_disable_auto_consent: true }));

    await userEvent.click(screen.getByRole("switch"));

    expect(onChange).toHaveBeenCalledWith({ enabled: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is held for an admin while it is off", () => {
    setting(consent({ may_disable_auto_consent: true }));

    expect(screen.getByRole("switch")).toBeDisabled();
  });

  it("is not drawn for an editor", () => {
    const { container } = setting(consent());

    expect(container).toBeEmptyDOMElement();
  });
});

describe("pinnable", () => {
  it.each([
    ["not_needed", true],
    ["consented", true],
    ["withdrawn", true],
    ["pending", false],
    ["declined", false],
  ] as const)("a %s version may be pinned: %s", (state, expected) => {
    expect(pinnable({ consent_state: state } as ArtifactVersion)).toBe(expected);
  });
});
