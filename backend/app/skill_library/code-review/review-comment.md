# Comment templates

Fill these in rather than writing from scratch - the shape is what makes a
review readable, and consistency is what makes it fast to read.

## Blocking, with a fix

> This returns `None` when `rows` is empty, and `_render` indexes it on the
> next line - an empty result is a 500 rather than an empty page.
>
> ```suggestion
> if not rows:
>     return []
> ```

## Blocking, no obvious fix

> Two requests arriving together both pass this check and both insert, because
> nothing holds the row between the read and the write. I do not have a good
> answer that keeps the current shape - worth talking through.

## Non-blocking

> nit: `data` could be `pending_invoices` - it is the only thing in this
> function that does not say what it holds.

## Approving with a note

> Approving. The retry loop is worth a follow-up: three attempts with no
> backoff will hammer a service that is already struggling, but that is not
> new in this change.
