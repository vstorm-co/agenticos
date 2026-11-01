import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useTableImageUpload } from "./use-table-image-upload";
import { uploadTableImage } from "@/lib/tables-api";
vi.mock("@/lib/tables-api", () => ({ uploadTableImage: vi.fn() }));
it("refuses an upload without a table and returns a scoped media reference when admitted", async () => {
  const file = new File(["png"], "image.png", { type: "image/png" });
  const missing = renderHook(() => useTableImageUpload());
  await expect(missing.result.current(file)).rejects.toThrow("Could not paste the image");
  expect(uploadTableImage).not.toHaveBeenCalled();
  vi.mocked(uploadTableImage).mockResolvedValueOnce({ id: "image", url: "/scoped-image" });
  const existing = renderHook(() => useTableImageUpload("table"));
  await expect(existing.result.current(file)).resolves.toEqual({
    id: "image",
    url: "/scoped-image",
  });
});
