# The permission catalog

Everything a member can be allowed to do, how far each permission reaches, and
how the built-in roles are composed from them.

See [Permissions](../permissions.md) for the explanation and for how the four
layers combine; this page is the generated reference.

::: app.core.permissions

## Resolving access to one row

Not generated. `app/services/` is an implicit namespace package - it has no
`__init__.py` - so the static collector cannot traverse into it, and a reference
page that silently omitted half its symbols would be worse than one that says
where to look.

The formula and every refusal it makes are documented in
[Permissions](../permissions.md#how-the-layers-combine). The source is
[`app/services/access.py`](https://github.com/vstorm-co/agenticos/blob/main/backend/app/services/access.py),
which carries the reasoning in its docstrings.
