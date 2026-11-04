import { describe, expect, it } from "vitest";
import { formPageOf } from "./form-page-config";
import { formButtonStyle } from "./form-surface";
describe("form presentation", () => {
  it("accepts incomplete drafts and keeps supported appearance choices", () => {
    expect(formPageOf({}, { title: "Form", submit: "Submit" })).toMatchObject({
      title: "Form",
      submit_label: "Submit",
      description: null,
      fields: [],
      appearance: { width: "standard", layout: "card" },
    });
    expect(
      formPageOf(
        {
          title: "Brief",
          description: "Welcome",
          submit_label: "Send",
          appearance: { width: "wide", layout: "plain", accent: "#123456" },
        },
        { title: "Form", submit: "Submit" },
      ),
    ).toMatchObject({
      title: "Brief",
      appearance: { width: "wide", layout: "plain", accent: "#123456" },
    });
  });
  it("keeps button labels readable and refuses CSS expressions", () => {
    expect(formButtonStyle("#ffffff")).toEqual({ backgroundColor: "#ffffff", color: "#000000" });
    expect(formButtonStyle("#000000")).toEqual({ backgroundColor: "#000000", color: "#ffffff" });
    expect(formButtonStyle("url(example)")).toBeUndefined();
    expect(formButtonStyle(null)).toBeUndefined();
  });
});
