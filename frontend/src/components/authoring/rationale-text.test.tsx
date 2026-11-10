import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { RationaleText } from "./evidence-list";

const FIRST = "e38ca3e9-40c1-4b2a-9c1d-0123456789ab";
const SECOND = "7a1b2c3d-1111-4222-8333-444455556666";
const EVIDENCE = [
  { run_id: FIRST, quote: "90 days" },
  { run_id: SECOND, quote: "No idea" },
];

it("turns run ids in a rationale into numbered conversations, and leaves the rest alone", () => {
  const { container } = render(
    <RationaleText
      text={`Readers in runs ${FIRST}, ${SECOND} and run e38ca3e9 asked; deadbeef is a word and ${"f".repeat(8)}-0000-4000-8000-000000000000 is gone.`}
      evidence={EVIDENCE}
    />,
  );
  expect(container).toHaveTextContent(
    "Readers in conversation 1, conversation 2 and conversation 1 asked; deadbeef is a word and a conversation is gone.",
  );
  expect(screen.getAllByRole("link", { name: "conversation 1" })[0]).toHaveAttribute(
    "href",
    `/runs?run=${FIRST}`,
  );
  expect(container).not.toHaveTextContent(FIRST);
});

it("links a conversation inside the Improve wizard", () => {
  render(
    <RationaleText
      text={`See run ${SECOND}.`}
      evidence={EVIDENCE}
      conversations={{ [SECOND]: "c2" }}
    />,
  );
  expect(screen.getByRole("link", { name: "conversation 2" })).toHaveAttribute("href", "/chat/c2");
});

it("names a run by the label the improver read it under", () => {
  render(
    <RationaleText
      text={`See run ${FIRST} and run ${SECOND}.`}
      evidence={[
        { run_id: FIRST, quote: "Delivery is free", source: "test_question", number: 2 },
        { run_id: SECOND, quote: "No idea", source: "conversation", number: 1 },
      ]}
    />,
  );
  expect(screen.getByRole("link", { name: "test question 2" })).toHaveAttribute(
    "href",
    `/runs?run=${FIRST}`,
  );
  expect(screen.getByRole("link", { name: "conversation 1" })).toBeInTheDocument();
});
