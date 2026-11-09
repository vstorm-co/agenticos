import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./skill-checks-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ id: "c-1" });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "c-1" });
});

describe("the skill checks client", () => {
  it("prices, starts and reads a check under its skill", async () => {
    const body = { fork_id: null, proposal_id: "p-1" };

    await api.estimateSkillCheck("s-1", body);
    await api.startSkillCheck("s-1", body);
    await api.getSkillCheck("s-1", "c-1");

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks/estimate", body);
    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks", body);
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s-1/checks/c-1");
  });

  it("lists a line's newest checks, main's or a fork's", async () => {
    await api.listSkillChecks("s-1", null);
    await api.listSkillChecks("s-1", "f-1");

    expect(apiClient.get).toHaveBeenCalledWith("/skills/s-1/checks?limit=20");
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s-1/checks?limit=20&fork_id=f-1");
  });

  it("lists a later page of a line's checks", async () => {
    await api.listSkillChecks("s-1", "f-1", 2);

    expect(apiClient.get).toHaveBeenCalledWith("/skills/s-1/checks?limit=20&fork_id=f-1&skip=40");
  });

  it("stops a running check", async () => {
    await api.cancelSkillCheck("s-1", "c-1");

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks/c-1/cancel", {});
  });

  it("decides a check through the check, never around it", async () => {
    await api.applySkillCheck("s-1", "c-1", { pin_worse: true });
    await api.discardSkillCheck("s-1", "c-1");
    await api.forkSkillCheck("s-1", "c-1", { name: "Prints", agent_ids: ["a-1"] });

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks/c-1/apply", {
      pin_worse: true,
    });
    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks/c-1/discard", {});
    expect(apiClient.post).toHaveBeenCalledWith("/skills/s-1/checks/c-1/fork", {
      name: "Prints",
      agent_ids: ["a-1"],
    });
  });

  it("lists the checks waiting for a person across the organization", async () => {
    await api.listSkillChecksAwaiting();

    expect(apiClient.get).toHaveBeenCalledWith("/skill-checks/awaiting");
  });
});
