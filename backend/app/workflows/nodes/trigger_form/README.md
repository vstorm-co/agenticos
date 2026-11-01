# trigger.form

A workflow anyone with its link starts by filling in a form. Publishing a
version with this trigger gives the workflow a public page at
`<console>/f/<token>`: its **title**, **description** and one input per declared
field, with the **submit label** on the button. A submission that fits the
fields starts one run, as the member who published the version, and the page
shows the **success message**; one that does not is answered with the fields
that are wrong, and starts nothing.

The link is the page's only credential. It survives every publish of the same
node, and **New link** on the workflow's trigger panel replaces it - the old one
then answers as if there were no form. Pausing the trigger closes the page.

## Limits

A page is read and submitted through the deployment's own address, counted per
form: `RATE_LIMIT_HOSTED_PAGE_PER_MINUTE` for reading it and
`RATE_LIMIT_FORM_SUBMISSIONS_PER_MINUTE` for submitting. Each submission is a run
like any other, so the organization's admission quota and the workflow's own
limits hold too. A hidden field a person never sees is the page's spam trap: a
submission that fills it in is thanked and starts nothing.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `WorkflowInputPayload` | `payload`, typed by the declared fields; `triggered_by` (`form`) |
