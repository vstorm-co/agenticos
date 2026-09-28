---
title: "Write product descriptions from a catalogue file"
description: "Attach a small synthetic products.csv and have an agent write one listing description per row, flagging the row that is missing a required attribute instead of inventing it."
---

# Write product descriptions from a catalogue file

Attach a small catalogue file to a plain chat agent bound to a listing-copy
skill, and check that it writes one description per product without
inventing anything the spec sheet does not state. One row is deliberately
missing a required attribute, so you can check that the agent flags the gap
rather than filling it in. This is a procedure to run, with one recorded run
as a reference.

## What you need

- A [running installation](../install.md) with a model profile.
- No sandbox or embedding model — a plain chat agent with the
  [skills capability](../reference/capabilities.md#skills) is enough; the
  CSV is small enough to be pasted into the prompt as text.
- Optional reading: **Skills → Skill gallery → e-commerce** has a
  `Product description writer` skill with the same rules this page uses, and
  the `ecommerce/listing-writer` agent template in the same gallery shows a
  fuller agent built around it, with knowledge and MCP connections added.
  This page's skill is written from that entry's content.

## Prepare the input

Save this as `products.csv`. Four rows are complete; `FW-104`'s `material`
column is deliberately blank — that is the gap this fixture is built to
test.

```csv
sku,name,category,material,size_run,weight_g,fit_note,care,box_contents
FW-101,Harbor Rain Jacket,Outerwear,recycled nylon 100%,S-XXL,410,true to size,machine wash cold,jacket and stuff sack
FW-102,Harbor Wool Beanie,Accessories,merino wool 100%,one size,80,one size fits most,hand wash cold,beanie only
FW-103,Harbor Steel Water Bottle,Drinkware,stainless steel,650 ml,320,not applicable,dishwasher safe lid only,bottle and lid
FW-104,Harbor Canvas Tote,Bags,,38 x 42 x 10 cm,260,not applicable,spot clean,tote bag only
FW-105,Harbor Trail Socks (2-pack),Apparel,merino wool blend 60%,S/M and L/XL,60,true to size,machine wash cold,two pairs of socks
```

Save this as a skill, in **Skills → New skill** — name it
`listing-copy-from-spec`, adapted from the gallery's
`ecommerce/product-description-writer`:

```text
Copy that describes a product the customer does not receive is the most
expensive sentence in e-commerce.

## Work only from the spec

Every claim traces to the spec sheet, the supplier data or a photograph. If
the material is not stated, the description does not name a material.

## The shape

One line saying what it is and who it is for; three to five bullets of
concrete attributes with numbers; one short paragraph on use; then the full
specification as given.

## Concrete beats enthusiastic

"320 gsm, pre-shrunk, fits true to size" outperforms "premium quality".
Numbers survive translation, reduce returns and answer the question that
would otherwise become a support ticket.

## Always include

Dimensions with units, materials, care, what is in the box, and — for
anything worn — the fit note. Missing fit information is the single largest
driver of apparel returns.

## Never

Claim a certification, a country of origin, a health benefit or a
compatibility that the source does not state.
```

## Build the agent

1. Create an agent in **Agents → New agent** and select your model profile.
2. In **Toolbox**, enable **Skills** and bind `listing-copy-from-spec`.
3. Set the instructions below, then **Publish**.

```text
You write product listing descriptions from an attached catalogue file.
Follow the bound listing-copy-from-spec skill for shape and rules.
Write one description per row of the attached CSV.
If a row is missing an attribute the skill says to always include, do not
invent it: name it as missing in that product's description instead.
Return the result as a markdown table: sku, name, then the description.
```

## Run it

Open a new chat with the agent, attach `products.csv` and send:

```text
Write listing descriptions for every product in the attached catalogue.
```

## Check the result

| Check | Reference |
| --- | --- |
| Row count | Five descriptions, one per SKU |
| Numbers | Weights, dimensions and capacities match the CSV exactly, with units |
| FW-104's missing material | Flagged as missing in that description, no material named |
| Fit note present | On FW-101, FW-102 and FW-105 — the three worn or wearable items |
| Never-claimed attributes | No certification, country of origin, health benefit or compatibility claim anywhere |
| Same request with no file attached | The agent says the file is missing and invents no catalogue |

Check FW-104 first — a missing attribute silently filled in is the failure
this fixture exists to catch.

!!! example "Recorded on v0.0.504, 25 September 2026"

    Model: Claude Sonnet 4.6 through OpenRouter. The agent loaded the bound
    skill, then wrote five descriptions in one reply, one per row. Every
    number — 650 ml, 320 g, 38 x 42 x 10 cm, 60% merino, S/M and L/XL — matched
    the CSV. For FW-104 it wrote "Material composition is not specified in the
    product data and has not been stated in this listing" instead of naming a
    fabric. Fit notes appeared on the jacket, the beanie and the socks; no
    certification, origin or health claim appeared anywhere. Cost: 0.053 USD.

    With no file attached, the agent still loaded the skill, then said "I
    don't see any attached catalogue file or CSV in your message" and asked
    for it, instead of writing descriptions from nothing.

## When it goes wrong

- **A material or dimension is invented for FW-104.** The skill's "Never"
  section is being ignored; repeat the instruction in the agent's own
  instructions field, not only in the skill.
- **The agent calls `load_capability` with the wrong id and the turn ends in
  an error.** This happened during verification when the skill was bound
  under the exact name and casing used by the gallery entry
  (`Product description writer`) — the model twice guessed a different id
  and the turn ended in `UnexpectedModelBehavior` rather than a normal
  refusal. Recreating the same content as a new skill under a plain,
  lowercase, hyphenated name fixed it every time it was retried. Naming the
  skill's exact stored name in the agent's instructions removes the guess, as
  [contract review](contract-review.md) describes; if a skill installed from
  the gallery still hits it, copy its body into a new skill with a plain
  name.
- **The fit note is missing on a worn item.** Ask which attribute the skill's
  "Always include" section names for that row; a missing fit note is the
  return driver the skill exists to prevent.
- **The reply skips a row.** Ask for the row count before trusting the table;
  five rows in, five descriptions out.

## Record the trial

Keep the CSV, the skill body, the five descriptions, the agent version and
the run in Activity. Keep a run where the missing attribute was invented, if
one happens — it is the clearest evidence the skill's wording needs
tightening.

A person still decides whether a description is fit to publish and follows
up on the flagged gap before the listing goes live; the check above catches
an invented fact, not a dull one.

## Next steps

For a live catalogue, bind a [knowledge collection](set-up-knowledge-base.md)
of supplier spec sheets instead of pasting rows, and add the
`ecommerce/review-response` skill from the same gallery shelf to answer
customer questions about a product with the same source discipline.
