import { render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ImprovementStartRedirect } from "./improvement-start-redirect";
const state = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: state.replace }),
  useSearchParams: () => state.params,
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.params = new URLSearchParams();
});
it("opens the start modal over the builder from a legacy link", () => {
  render(<ImprovementStartRedirect agentId="a1" />);
  expect(state.replace).toHaveBeenCalledWith("/agents/a1?improve=new");
});
it("keeps a legacy link's dataset, baseline and resume intent", () => {
  state.params = new URLSearchParams("dataset=ds-1&baseline=1&resume=1");
  render(<ImprovementStartRedirect agentId="a1" />);
  expect(state.replace).toHaveBeenCalledWith(
    "/agents/a1?improve=baseline-resume&improveDataset=ds-1",
  );
});
