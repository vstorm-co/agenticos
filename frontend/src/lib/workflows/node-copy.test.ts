import { createTranslator, type AbstractIntlMessages } from "next-intl";
import { expect, it } from "vitest";
import pl from "../../../messages/pl.json";
import { logStepName } from "./node-copy";

const messages: AbstractIntlMessages = pl;
const t = createTranslator({ locale: "pl", messages, namespace: "workflowNodes" });

it("translates a default log label without consulting a newer draft", () => {
  expect(logStepName({ step_label: "Manual", step_definition_id: "core.input" }, t)).toBe(
    pl.workflowNodes.node.core_input.name,
  );
});

it.each([null, undefined, "vendor.new"])("keeps a custom, legacy or unknown label (%s)", (id) => {
  expect(logStepName({ step_label: "Manual", step_definition_id: id }, t)).toBe("Manual");
});
