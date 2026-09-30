# transform.*

The **Transform** steps reshape a list of objects without a code step. Each takes
`items` - a list bound from an earlier step - and most hand on `items` in the same
shape, so they chain: filter, sort, limit, then write the rows.

| Step | Does |
|---|---|
| `transform.edit_fields` | Sets fields from expressions over each item, removes others, or keeps only the ones set |
| `transform.sort` | Sorts by fields in turn, ascending or descending; items missing a key go last |
| `transform.limit` | Keeps the first or the last items |
| `transform.remove_duplicates` | Keeps the first of each set of items equal on the fields named, or on the whole item |
| `transform.aggregate` | Collects each field's values across the items into one list per field |
| `transform.split_out` | Turns a list inside each item into items of their own |
| `transform.summarize` | Counts, sums, averages, finds the least or greatest, by group |
| `transform.date_time` | Now, or a bound moment moved by an amount, written out in a timezone |
| `transform.crypto` | Hashes or encodes text, or makes a UUID or random hex |

## Missing keys

A field is a dotted path, `customer.email`. An item without it is never an error:
Sort puts it last, Remove duplicates treats "missing" as a value of its own,
Aggregate and Summarize leave it out, Split out keeps the item as it is, and Edit
fields sets `null` where its expression finds nothing. A key holding `null` is a
value, not a missing key.

## Why not a code step

Every one of these is a line of Python, and a code step would do. But a code step
is opaque on the canvas, needs a sandbox, and cannot be type-checked at publish;
these are pure, typed and visible, and their output shape is known to the steps
that bind to it.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `items` binding (`value` for Date & time, `text` for Crypto) |
| `out` | output | `ItemsOutput`, or the step's own | `items`, or `values` / `value` |
