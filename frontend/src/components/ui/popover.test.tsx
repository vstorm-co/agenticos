import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "./popover";

it("opens at its final size instead of transitioning into it", () => {
  // A panel sized from its trigger learns that width a frame after it mounts;
  // with the panel's duration transitioning every property it shrank visibly
  // from the width of the screen.
  render(
    <Popover open>
      <PopoverTrigger>Pick</PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)]">Choices</PopoverContent>
    </Popover>,
  );
  expect(screen.getByText("Choices")).toHaveClass("transition-none");
});
