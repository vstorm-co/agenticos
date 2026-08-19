import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FileDropOverlay } from "./file-drop-overlay";

/**
 * The copy is the caller's, so these are the chat's words rather than this
 * component's: it attaches a file to a message, and `/context` makes a file out
 * of one. What is shared is everything else - and the reason this moved out of
 * `components/chat` is that the everything else was about to be written twice.
 */
const COPY = { title: "Drop files to attach", hint: "Up to 25MB per file" };

describe("the page-wide drop target", () => {
  it("shows nothing until something is being dragged over the page", () => {
    render(<FileDropOverlay active={false} {...COPY} />);

    expect(screen.queryByTestId("file-drop-overlay")).toBeNull();
  });

  it("says what will happen and what the file may weigh", () => {
    // The limit belongs here rather than in the error afterwards: a 60MB video
    // that is refused after the drag is a round trip nobody needed to make.
    render(<FileDropOverlay active {...COPY} />);

    expect(screen.getByText("Drop files to attach")).toBeInTheDocument();
    expect(screen.getByText("Up to 25MB per file")).toBeInTheDocument();
  });

  it("renders on the body, not where it was written", () => {
    // `fixed` is measured against the nearest transformed ancestor rather than
    // the viewport, and this is rendered from inside the composer - one
    // `backdrop-blur` on a wrapper above it would shrink the overlay to a corner.
    const { container } = render(<FileDropOverlay active {...COPY} />);

    expect(container).toBeEmptyDOMElement();
    expect(document.body).toContainElement(screen.getByTestId("file-drop-overlay"));
  });

  it("says nothing to a screen reader", () => {
    // A drag is a pointer gesture nobody can perform from a keyboard, so this can
    // only ever be noise. The button beside the composer is the accessible route.
    render(<FileDropOverlay active {...COPY} />);

    expect(screen.getByTestId("file-drop-overlay")).toHaveAttribute("aria-hidden", "true");
  });
});
