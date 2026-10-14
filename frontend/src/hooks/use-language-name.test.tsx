import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useLanguageName } from "./use-language-name";

describe("useLanguageName", () => {
  it("names a language in the reader's language, and answers an unknown code with itself", () => {
    const { result } = renderHook(() => useLanguageName());
    expect(result.current("pl")).toBe("Polish");
    expect(result.current("qq")).toBe("qq");
  });
});
