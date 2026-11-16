import { expect, it, vi } from "vitest";
import AssistantSettingsPage from "./page";
const redirect = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ redirect }));
it("preserves legacy personal-preference links through Account", () => {
  AssistantSettingsPage();
  expect(redirect).toHaveBeenCalledWith("/settings/account");
});
