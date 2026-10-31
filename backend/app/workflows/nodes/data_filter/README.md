# data.filter

**Filter a list**: keep the items of a bound list for which a JMESPath condition
holds, in their order, and say how many were dropped. The condition reads each
item as `item` and its position as `index` - `item.score > \`50\``. A condition
that fails on an item fails the step with that item's index.

## Why it is its own step

Looping over a list only to skip most of it runs a step per item for nothing. A
filter before the loop keeps the loop to the items that matter, and a filter
before a table write keeps the write to the rows that should land.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `items` binding |
| `out` | output | `DataFilterOutput` | `items`, `dropped` |
