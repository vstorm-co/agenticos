# data.combine

**Combine lists**: make one list of two bound lists, `first` and `second`.

| Mode | What it does |
|---|---|
| `append` | the second list after the first |
| `by_position` | the objects at the same position merged, as far as the shorter list goes |
| `by_key` | each object of the first merged with the second's object of the same `key`; one with no match kept as it is |

Where both objects have a field, the second's value wins. Merging item by item
needs both lists to hold objects, and fails with `COMBINE_NEEDS_OBJECTS`
otherwise.

## Why it is not Merge

**Merge** rejoins branches of one decision, of which exactly one ran. Combining
lists is about data both branches, or two steps, made: the leads from a form and
their scores from a model, matched by the lead's id.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `first` and `second` bindings |
| `out` | output | `DataCombineOutput` | `items` |
