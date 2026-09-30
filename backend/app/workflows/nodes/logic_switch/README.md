# logic.switch

**Switch**: send the run down one of many branches. Each rule has a name - the
branch's port - and a JMESPath condition over the bound `value`. The rules are
tried in order and the first that holds takes the run; `otherwise` takes it when
none does. The step hands on the branch it chose and the value, unchanged.

## Why it is not a chain of If steps

A decision with five answers read as four nested **If / else** steps is hard to
follow and easy to get wrong: the order the conditions run in is the order they
nest in. A switch states the order once, on one step, and its branches rejoin at a
single **Merge**, which accepts them because exactly one is ever taken.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `in` | input | - | the `value` binding |
| one per rule | output | `LogicSwitchOutput` | `branch`, `value` |
| `otherwise` | output | `LogicSwitchOutput` | `branch`, `value` |
