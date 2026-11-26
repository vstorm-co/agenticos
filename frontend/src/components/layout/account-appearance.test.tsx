import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountAppearance } from "./account-appearance";
const hook = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-account-appearance", () => ({ useAccountAppearance: hook }));
it("synchronizes appearance while mounted", () => {
  render(<AccountAppearance />);
  expect(hook).toHaveBeenCalled();
});
