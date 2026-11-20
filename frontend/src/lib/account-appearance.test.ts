import { beforeEach, expect, it } from "vitest";
import { appearanceChosenBy } from "./account-appearance";
import { useThemeStore } from "@/stores/theme-store";

beforeEach(() => useThemeStore.setState({ theme: "system", look: "standard", editRevision: 0 }));

it("applies only this platform's successful choices without re-enqueuing a save", () => {
  appearanceChosenBy(
    "agenticos_set_my_preferences",
    JSON.stringify({ theme: "dark", look: "glass", locale: "pl" }),
  );
  expect(useThemeStore.getState()).toMatchObject({ theme: "dark", look: "glass", editRevision: 0 });
});

it.each(["other_set_my_preferences", "set_my_preferences"])("ignores %s", (name) => {
  appearanceChosenBy(name, '{"theme":"dark","look":"glass"}');
  expect(useThemeStore.getState().theme).toBe("system");
});

it.each([
  "not JSON",
  "null",
  "true",
  "{}",
  '{"error":"refused"}',
  '{"theme":"unknown","look":"unknown"}',
  '{"theme":null,"look":null}',
])("does not adopt refusal/default values: %s", (result) => {
  appearanceChosenBy("agenticos_set_my_preferences", result);
  expect(useThemeStore.getState()).toMatchObject({ theme: "system", look: "standard" });
});

it.each(["light", "system"])("accepts %s", (theme) => {
  useThemeStore.setState({ theme: "dark" });
  appearanceChosenBy("agenticos_set_my_preferences", JSON.stringify({ theme, look: "paper" }));
  expect(useThemeStore.getState().theme).toBe(theme);
});
