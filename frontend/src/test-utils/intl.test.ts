import { describe, expect, it } from "vitest";

import { keyTranslations } from "./intl";

describe("keyTranslations", () => {
  it("returns keys, and carries the members the real t has", () => {
    const t = keyTranslations()("ns");

    expect(t("k")).toBe("k");
    // The members a bare `(key) => key` mock lacks: a component reading a message
    // with a tag calls `t.rich`, and the missing method throws inside an
    // unrelated spec (#612).
    expect(t.rich("k")).toBe("k");
    expect(t.markup("k")).toBe("k");
    expect(t.has("k")).toBe(true);
  });

  it("preserves a caller's namespaced key format", () => {
    const t = keyTranslations((ns, key) => (ns ? `${ns}.${key}` : key))("pages");

    expect(t("title")).toBe("pages.title");
    expect(t.rich("title")).toBe("pages.title");
  });
});
