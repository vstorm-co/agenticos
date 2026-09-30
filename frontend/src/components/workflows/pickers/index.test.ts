import { describe, expect, it } from "vitest";

import * as pickers from "./index";

describe("pickers barrel", () => {
  it("re-exports every resource picker the property panel imports", () => {
    expect(typeof pickers.CollectionPicker).toBe("function");
    expect(typeof pickers.AgentVersionPicker).toBe("function");
    expect(typeof pickers.TableColumnPicker).toBe("function");
    expect(typeof pickers.SecretPicker).toBe("function");
  });
});
