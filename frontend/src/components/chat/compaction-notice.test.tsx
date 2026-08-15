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
