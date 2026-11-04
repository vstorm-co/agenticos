import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationStore } from "@/stores";
import { useWorkOnStore } from "@/stores/work-on-store";
import { LocalCodingSettings } from "./local-coding-settings";
const env = vi.hoisted(() => ({ refetch: vi.fn(), error: null as Error | null, available: true }));
vi.mock("@/hooks/use-desktop", () => ({
  useLocalCodingOptions: () => ({
    data: env.available
      ? {
          current_model: "fast",
          current_effort: "low",
          models: [
            { value: "fast", name: "Fast", efforts: [{ value: "low", name: "Low" }] },
            { value: "deep", name: "Deep", efforts: [{ value: "high", name: "High" }] },
          ],
        }
      : undefined,
    error: env.error,
    refetch: env.refetch,
    isFetching: false,
  }),
}));
beforeEach(() => {
  env.available = true;
  env.error = null;
  env.refetch.mockReset();
  useConversationStore.setState({ currentConversationId: "topic" });
  useWorkOnStore.setState({ codingByConversation: {}, codingPreferencesByConversation: {} });
});
it("saves actual choices for this topic and clears an effort the next model does not offer", async () => {
  render(<LocalCodingSettings harness="codex" />);
  const user = userEvent.setup();
  await user.selectOptions(screen.getByRole("combobox", { name: "Reasoning level" }), "low");
  expect(useWorkOnStore.getState().codingFor("topic")).toBe("codex");
  expect(useWorkOnStore.getState().codingPreferencesFor("topic").effort).toBe("low");
  await user.selectOptions(screen.getByRole("combobox", { name: "Coding model" }), "deep");
  expect(useWorkOnStore.getState().codingPreferencesFor("topic")).toEqual({
    model: "deep",
    effort: null,
  });
  await user.selectOptions(screen.getByRole("combobox", { name: "Reasoning level" }), "high");
  expect(useWorkOnStore.getState().codingPreferencesFor("topic")).toEqual({
    model: "deep",
    effort: "high",
  });
  expect(useWorkOnStore.getState().codingPreferencesFor("another")).toEqual({
    model: null,
    effort: null,
  });
});
it("keeps an unavailable saved model visible instead of silently substituting one", () => {
  useWorkOnStore.getState().setCodingPreferences("topic", { model: "removed", effort: "max" });
  render(<LocalCodingSettings harness="claude_code" />);
  expect(screen.getByRole("combobox", { name: "Coding model" })).toHaveValue("removed");
  expect(screen.getByRole("combobox", { name: "Reasoning level" })).toHaveValue("max");
  expect(useWorkOnStore.getState().codingPreferencesFor("topic").model).toBe("removed");
});
it("offers an explicit retry after a settings failure", async () => {
  env.available = false;
  env.error = new Error("Unavailable");
  render(<LocalCodingSettings harness="claude_code" />);
  await userEvent.click(screen.getByRole("button"));
  expect(env.refetch).toHaveBeenCalledOnce();
});
