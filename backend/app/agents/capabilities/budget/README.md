# Budget

Two mechanisms that are deliberately separate:

- **`SpendLedger`** - accounting. What a run consumed, in tokens and dollars.
- **`BudgetGuard`** - enforcement. Refuses to issue a model request once a limit
  is reached.

Enforcement happens *before* each request. Checking afterwards means the request
that broke the budget was already paid for, and a runaway loop overshoots by one
expensive call every time.

Not registered in the capability registry: every agent gets a budget guard,
always, built by the factory from the spec's `budget` block and the
organization's limit. Making it optional would make "an agent with no spending
limit" a thing someone could configure by accident.

Prices come from [`genai-prices`](https://github.com/pydantic/genai-prices),
not from a table here. There was a table - nine models, hand-maintained - and
it was wrong in a way a table cannot be right: Gemini 2.5 Pro charges one rate
below a 200k-token context and double above it, and a flat
dollars-per-million entry can only hold one of the two. It held the cheaper
one, so long-context runs were reported at half their cost and the budget that
exists to stop a runaway loop let it run twice as far. Cached tokens had the
same problem in the other direction: billed at the full input rate when they
cost a fraction of it.

The lookup uses the snapshot bundled with the package and never touches the
network. A self-hosted deployment should not make an outbound request because
somebody ran an agent; refreshing prices is a dependency bump, which is a
change someone reviews.

A model the package does not know is recorded at zero cost **with a flag**,
because a total that quietly under-reports is worse than one visibly marked
incomplete.

One ledger per run, and a run can contain several agents: a delegation runs a
second agent's whole conversation inside a turn of the first, against this ledger,
which is what makes the parent's cap bind on it. So each entry is stamped with two
things and `book` is the only way in: the delegation that booked it (`booked_to`,
`SpendLedger.share_of`), for the delegation panel, and the nearest agent-row it
bills to (`billed_to`, `SpendLedger.billed_share_of`), for the month. The two are
equal for a published delegate's own requests and differ only under an inline
specialist, which has no row of its own - its spend bills to its nearest published
ancestor's month while its panel keeps its own share (agenticos#228). That is not
bookkeeping for its own sake - a delegate's own run row is what answers "what did
the researcher cost this month", and the alternative (subtracting the shared total
across the delegation) put the parent's later spend on the child and a delegate's
delegates inside its own share. Attribution keeps one set of prices for every
question; the second lookup that pricing a task handle's usage would need is the
thing `BudgetGuard.for_delegate` exists to prevent.
