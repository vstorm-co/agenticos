import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  VoiceApprovalCard,
  VoiceApprovalSettled,
  VoiceApprovalUnavailable,
} from "./voice-approval-card";

const APPROVAL = {
  id: "a1",
  tool: "send_invoice",
  args: { customer: "Ahmad", amount_eur: 120, paid: false },
  said: "send an invoice for 120 euros to Acme",
  deadline: 61_000,
  timeoutSeconds: 60,
};

describe("VoiceApprovalCard", () => {
  it("renders the arguments verbatim and what the caller said", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide onDecide={vi.fn()} />);
    const card = screen.getByRole("group", { name: "Approve Send Invoice?" });
    expect(within(card).getByText("Approval needed")).toBeInTheDocument();
    expect(within(card).getByText("send_invoice")).toBeInTheDocument();
    const customer = within(card).getByText("customer").parentElement as HTMLElement;
    expect(within(customer).getByText("Ahmad")).toBeInTheDocument();
    expect(within(card).getByText("120")).toBeInTheDocument();
    expect(within(card).getByText("false")).toBeInTheDocument();
    expect(within(card).getByText(/You said/)).toHaveTextContent(
      "send an invoice for 120 euros to Acme",
    );
    expect(within(card).getByText(/Speech can be misheard/)).toBeInTheDocument();
    // The exact JSON the tool gets, one click away.
    expect(within(card).getByText("Exact JSON sent to the tool")).toBeInTheDocument();
  });

  it("names a tool the catalog knows by its name", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, tool: "publish_artifact", said: null }}
        now={1_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("group", { name: "Approve Published page?" })).toBeInTheDocument();
    expect(screen.queryByText(/You said/)).toBeNull();
  });

  it("counts down to the automatic denial", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={31_000} canDecide onDecide={vi.fn()} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText("Auto-deny in 0:30")).toBeInTheDocument();
  });

  it("counts down over as long as the server gave", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, deadline: 31_000, timeoutSeconds: 30 }}
        now={16_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "30");
    expect(bar).toHaveAttribute("aria-valuenow", "15");
    expect(bar.firstElementChild).toHaveStyle({ width: "50%" });
  });

  it("never counts below zero", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={90_000} canDecide onDecide={vi.fn()} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("approves and denies by button, never by voice", () => {
    const onDecide = vi.fn();
    render(<VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(onDecide.mock.calls).toEqual([[true], [false]]);
    expect(screen.getByText(/Saying “yes” to the agent doesn't approve/)).toBeInTheDocument();
  });

  it("brings itself into view when it appears", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(<VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide onDecide={vi.fn()} />);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    delete (Element.prototype as Partial<Element>).scrollIntoView;
  });

  it("offers no buttons to somebody who cannot decide, and no word about buttons", () => {
    render(
      <VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide={false} onDecide={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByText(/Only these buttons decide/)).toBeNull();
  });

  it("draws an empty bar rather than a broken one for a decision given no time", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, timeoutSeconds: 0, deadline: 0 }}
        now={1_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByRole("progressbar").firstElementChild).toHaveStyle({ width: "0%" });
  });

  it("wraps a long unbroken argument rather than pushing the card wider", () => {
    const long = "x".repeat(200);
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, args: { reference: long } }}
        now={1_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    const value = screen.getAllByText(long)[0] as HTMLElement;
    expect(value).toHaveClass("[overflow-wrap:anywhere]", "min-w-0");
    expect(value.parentElement).toHaveClass("grid-cols-[minmax(92px,auto)_minmax(0,1fr)]");
  });

  it("renders nested arguments as formatted JSON rather than [object Object]", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, args: { line: { sku: "A1", qty: 2 } } }}
        now={0}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getAllByText(/"sku": "A1"/).length).toBeGreaterThan(0);
    expect(screen.queryByText("[object Object]")).toBeNull();
  });
});

describe("VoiceApprovalSettled", () => {
  it.each([
    ["approved", "Approved by you"],
    ["denied", "Denied by you"],
    ["expired", "Denied automatically: no decision within 60 seconds"],
  ] as const)("keeps a %s approval as the record of what was decided", (outcome, text) => {
    render(<VoiceApprovalSettled settled={{ approval: APPROVAL, outcome }} />);
    const card = screen.getByRole("group", { name: text });
    expect(within(card).getByText("Ahmad")).toBeInTheDocument();
    expect(within(card).getByText(/You said/)).toBeInTheDocument();
    expect(within(card).queryByText(/Speech can be misheard/)).toBeNull();
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("leaves out what was said when nothing was heard", () => {
    render(
      <VoiceApprovalSettled
        settled={{ approval: { ...APPROVAL, said: null }, outcome: "approved" }}
      />,
    );
    expect(screen.queryByText(/You said/)).toBeNull();
  });
});

describe("VoiceApprovalUnavailable", () => {
  it("tells a caller who cannot approve, plainly, and offers to keep talking or move to text", () => {
    const onDismiss = vi.fn();
    const onEndCall = vi.fn();
    render(
      <VoiceApprovalUnavailable
        tool="send_invoice"
        args={{ customer: "Acme" }}
        onDismiss={onDismiss}
        onEndCall={onEndCall}
      />,
    );
    const card = screen.getByRole("group", { name: "Needs an approval you can't give here" });
    expect(
      within(card).getByText(/needs an approval you cannot give by voice/),
    ).toBeInTheDocument();
    expect(within(card).getByText("Acme")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep talking" }));
    fireEvent.click(screen.getByRole("button", { name: "End call, continue in text" }));
    expect(onDismiss).toHaveBeenCalledOnce();
    expect(onEndCall).toHaveBeenCalledOnce();
  });
});
