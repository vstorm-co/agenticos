import { expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { readConsoleExperience, saveConsoleExperience } from "./console-experience-api";
vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));
it("pins both reads and partial or whole resets to the chosen membership", async () => {
  await readConsoleExperience("org-one");
  expect(apiClient.get).toHaveBeenCalledWith("/users/me/console-experience", {
    headers: { "X-Organization-Id": "org-one" },
  });
  await saveConsoleExperience("org-one", { preferences: { inbox: null, greeting: false } });
  expect(apiClient.patch).toHaveBeenLastCalledWith(
    "/users/me/console-experience",
    { preferences: { inbox: null, greeting: false } },
    { headers: { "X-Organization-Id": "org-one" } },
  );
  await saveConsoleExperience("org-two", { preferences: null });
  expect(apiClient.patch).toHaveBeenLastCalledWith(
    "/users/me/console-experience",
    { preferences: null },
    { headers: { "X-Organization-Id": "org-two" } },
  );
});
