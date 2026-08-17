import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompactionNotice } from "./compaction-notice";

describe("CompactionNotice", () => {
  it("says nothing when nothing is being summarised", () => {
    // It sits above the composer, so a notice that lingered would push the input
    // down on every turn that never compacted.
    const { container } = render(<CompactionNotice compacting={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says what is being summarised while it happens", () => {
    // The whole point: compaction runs between two of the turn's model requests,
    // where nothing else streams, so the screen is otherwise indistinguishable
    // from a broken one.
    render(
      <CompactionNotice
        compacting={{ kind: "compaction_started", messages_before: 62, messages_after: null }}
      />,
    );

    expect(screen.getByText(/Summarising 62 earlier messages/)).toBeVisible();
  });

  it("counts one message as one", () => {
    render(
      <CompactionNotice
        compacting={{ kind: "compaction_started", messages_before: 1, messages_after: null }}
      />,
    );

    expect(screen.getByText(/Summarising 1 earlier message\b/)).toBeVisible();
  });

  it("still says something when the count is missing", () => {
    // The frame carries it, but a client must not go silent on the one field it
    // did not get - silence here reads as the failure this exists to rule out.
    render(
      <CompactionNotice
        compacting={{ kind: "compaction_started", messages_before: null, messages_after: null }}
      />,
    );

    expect(screen.getByText(/Summarising the conversation/)).toBeVisible();
  });

  it("says why nothing is being summarised, when nothing can be", () => {
    // The fixed overhead is already past the trigger, so no summary can get under
    // it and the platform refuses to buy one on every request for ever. It does
    // nothing - which on screen is indistinguishable from a setting that works.
    render(
      <CompactionNotice
        compacting={null}
        impossible={{
          kind: "compaction_impossible",
          messages_before: null,
          messages_after: null,
          overhead_tokens: 3_843,
          window_tokens: 5_000,
        }}
      />,
    );

    expect(screen.getByText(/3,843 tokens of the 5,000-token window/)).toBeVisible();
  });

  it("gives way the moment a summary actually runs", () => {
    // A summary that ran is the answer to the warning, and two notices about one
    // subject is one too many above a composer.
    render(
      <CompactionNotice
        compacting={{ kind: "compaction_started", messages_before: 8, messages_after: null }}
        impossible={{
          kind: "compaction_impossible",
          messages_before: null,
          messages_after: null,
          overhead_tokens: 3_843,
          window_tokens: 5_000,
        }}
      />,
    );

    expect(screen.getByText(/Summarising 8 earlier messages/)).toBeVisible();
    expect(screen.queryByText(/cannot run/)).toBeNull();
  });

  it("announces itself to a screen reader without stealing focus", () => {
    render(
      <CompactionNotice
        compacting={{ kind: "compaction_started", messages_before: 4, messages_after: null }}
      />,
    );

    const notice = screen.getByRole("status");
    expect(notice).toHaveAttribute("aria-live", "polite");
  });
});
