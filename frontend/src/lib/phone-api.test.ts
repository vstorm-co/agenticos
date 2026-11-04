import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { phoneApi } from "./phone-api";
import { phoneContact } from "@/test-utils/phone";
vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
it("sends only reviewed consent fields, excluding read-only contact metadata", async () => {
  const readContact = { ...phoneContact, id: "do-not-send", masked_number: "masked" };
  await phoneApi.saveContact(readContact);
  expect(apiClient.put).toHaveBeenCalledWith("/phone/contact", phoneContact);
});
it("uses authenticated same-origin call and transfer endpoints", async () => {
  await phoneApi.call({
    request_key: "key",
    endpoint_id: "endpoint",
    mode: "report",
    report: "Ready",
  });
  expect(apiClient.post).toHaveBeenCalledWith(
    "/phone/calls",
    expect.objectContaining({ request_key: "key", report: "Ready" }),
  );
  await phoneApi.hangup("c");
  await phoneApi.transfer("c", "member");
  await phoneApi.receipt("c");
  expect(apiClient.post).toHaveBeenCalledWith("/phone/calls/c/hangup", {});
  expect(apiClient.post).toHaveBeenCalledWith("/phone/calls/c/transfer", { contact_id: "member" });
  expect(apiClient.get).toHaveBeenCalledWith("/phone/calls/c");
});
