# Design an App around its job

Default to the kit: compose layout with `ao-stack`, `ao-row` and `ao-grid-*`, and let the kit supply type, spacing and color. Inline `style` is for run-time values only (a bar width, a chart height). Type scale and token choices below matter when you write your own CSS for a supplied brand or design.

Use a real audience, action and source. Keep supplied branding. Otherwise choose a restrained visual system that fits the subject; an operational view and an editorial report need different reading rhythms.

## Choose a composition

| Job                  | Useful starting structure                                    | Avoid                                                      |
| -------------------- | ------------------------------------------------------------ | ---------------------------------------------------------- |
| Explain a conclusion | A clear lead, one supporting graphic, evidence and caveats   | A grid of equal-weight statistic cards                     |
| Compare options      | Criteria beside ranked options; selected option detail       | A score with no visible calculation                        |
| Work through records | Search/filter, compact rows, selected record and next action | A wide spreadsheet squeezed onto a phone                   |
| Monitor change       | Few actionable measures, trends and exceptions               | A dashboard when there is no ongoing monitoring job        |
| Prepare a decision   | Inputs, computed consequences and assumptions                | A form that pretends to save or send without a real action |

The editorial brief and decision workbench templates are complete, offline examples with labelled demonstration data. The existing report/dashboard/live-table templates show the product's served helper classes. Adapt the composition and data; do not retain a supplier name or recommendation merely because it came with the example.

## Establish hierarchy

- Write a title naming the topic and a lead answering the reader's main question.
- Pick a comfortable text measure and a deliberate type scale. Use weight, alignment and space before adding more borders or color. Give exact numbers tabular figures and their units.
- Use one emphasis color for the primary action or selected state. Distinguish warning/error from decoration. Test the actual text/background pairs in both intended themes.
- Use diagrams or images where they explain the subject. A raster asset may come from the available image-generation capability, with an explicit brief for subject, framing and intended placement. Keep exact UI text, chart labels and figures in HTML/SVG.
- Use small multiples, a ranked list, an annotated chart or a split detail view where each fits. Equal cards are useful only when their content really is comparable.

## Make interaction credible

A control needs an observable result: a filter changes the list and its count, a criterion changes the score, a selected option opens detail, and reset restores a documented baseline. Keep the primary interaction usable in the first screen; let long evidence and secondary settings expand on demand.

Use native buttons, inputs, labels and tables. Provide focus styles and keyboard operation. A narrow screen may stack the controls above the result or show a record as a labelled row; it must retain the same information and actions. Do not disable zoom or hide essential controls behind hover.

## Define state and data

For each data source or external action, define loading, available, empty, unavailable and failure states as appropriate. Preserve a draft after a refused write. A local demonstration must say that its state is local to the page; it must not report a saved server change.

For each number, identify its source, period and unit. An illustrative model labels its inputs and formula. Missing values remain missing; a zero is a measurement, not a substitute for unknown. After filtering, recompute affected totals and state whether a ranking is based on the full dataset or only the displayed subset.

## Polish with evidence

Read the result as its recipient. Check a narrow phone, a large screen, a long name, an empty result and an unavailable source. Exercise the primary action using a keyboard. Inspect the actual publication rather than only a screenshot of an HTML file. Change one concrete defect at a time; keep the existing user's edits and working behavior.

## A report is an argument with inspectable evidence

Use the report template for an executive lead, a dominant measure, an annotated comparison and a compact source table. Its supplier scope changes the chart, denominator and selected totals together; its recommendation explicitly keeps the full-sample scope. Recompute rates from the selected underlying counts, not by averaging percentages. Identify illustrative fixtures in the opening and source note, rather than presenting them as a real system export.

For other Apps, sketch the primary interaction before writing the interface. A calculator starts with useful inputs and a visible result; a record workbench starts with a searchable list and selected detail; a report starts with the conclusion. Give the initial screen the final content hierarchy. Avoid filling a generic four-KPI dashboard when the requested job needs another structure.

Review the finished artifact as a recipient: the first screen should communicate its topic, main result and useful action without opening a settings panel. Check the primary interaction, long content and an empty selection. Keep exact labels selectable and charts accompanied by values. A polished screenshot cannot substitute for working controls or a correctly scoped data source.
