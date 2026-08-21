"""The migration chain has one head, and this test needs no database to say so.

Two branches each wrote a migration against a `main` that ended at `0043`, each
was green, and neither could see the other: `0044_agent_embed_key_version` (#552)
and `0044_audit_impersonator` (#943) both pointed at `0043_rag_document_source_path`.
Merged one after the other they made two heads, and `alembic upgrade head` answers
`Multiple head revisions are present` and exits 255 - so no deployment could
upgrade, and four cases in `tests/test_migrations.py` failed at once (#1059).

Nothing on either pull request could have caught it. The required checks ran
against a `main` holding only one of the two, and `make db-check` is
`alembic check`, which compares the models to the chain's head and says nothing
about how many heads there are.

So the guard lives here rather than in `tests/test_migrations.py`: that module
skips on a laptop with no Postgres, and a divergence is created by a merge on
somebody's machine long before CI's database ever sees it. `ScriptDirectory`
reads the files, and the files are the whole of the question.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _chain() -> ScriptDirectory:
    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_chain_has_exactly_one_head() -> None:
    heads = _chain().get_heads()
    assert len(heads) == 1, (
        f"{len(heads)} alembic heads: {', '.join(sorted(heads))}. Two migrations "
        "written against the same parent were merged one after the other; point "
        "the later one's down_revision at the earlier one."
    )


def test_no_two_migrations_claim_the_same_parent() -> None:
    """The same defect one step earlier, and it names both files.

    One head is what breaks the upgrade, so the test above is the one that
    matters. This one fails on the fork itself rather than on its consequence,
    which is the difference between a message naming the two revisions that
    collided and one naming the two heads they produced.
    """
    parents: dict[str, list[str]] = {}
    for revision in _chain().walk_revisions():
        down = revision.down_revision
        if down is None:
            continue
        for parent in (down,) if isinstance(down, str) else down:
            parents.setdefault(parent, []).append(revision.revision)

    forked = {parent: sorted(children) for parent, children in parents.items() if len(children) > 1}
    assert not forked, f"revisions sharing a parent: {forked}"
