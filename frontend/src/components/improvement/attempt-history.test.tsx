import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import { AttemptHistory } from "./attempt-history";

it("says what each earlier attempt came to, measured or not", () => {
  const [first] = SESSION.iterations;
  const { container } = render(
    <AttemptHistory
      session={{
        ...SESSION,
        iteration: 4,
        iterations: [
          { ...first!, id: "r1", number: 1, verdict: "regression" },
          { ...first!, id: "r2", number: 2, verdict: null, batch_id: "b2" },
          { ...first!, id: "r3", number: 3, verdict: null, batch_id: null },
          { ...first!, id: "r4", number: 4, verdict: null, batch_id: null },
        ],
      }}
    />,
  );
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "Attempt 1: the changes broke questions that worked.",
    "Attempt 2: changes proposed, not tested yet.",
    "Attempt 3: no change was proposed.",
  ]);
  expect(container).not.toHaveTextContent("Attempt 4");
});

it("says nothing on the first attempt", () => {
  const { container } = render(<AttemptHistory session={{ ...SESSION, iteration: 1 }} />);
  expect(container).toBeEmptyDOMElement();
});
