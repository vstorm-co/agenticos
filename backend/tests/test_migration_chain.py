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
    # The integration preserves already-issued revisions from both reviewed
    # branches. These exact forks are joined by explicit merge revisions; a new
    # sibling still fails here, even if a later accidental head masks it.
    assert forked == {
        "0159_default_organization": ["0160_datasets", "0160_user_profile"],
        "0178_eval_run_proposal_check": [
            "0174_case_score_agent_key",
            "0175_knowledge_gap_covered",
            "0176_eval_case_fault",
            "0177_dataset_case_anonymised_at",
            "0179_case_generation_drop_counts",
            "0182_eval_suite_pin",
            "0183_proposal_revision",
            "0187_job_api_key",
        ],
    }, f"unexpected revisions sharing a parent: {forked}"
    chain = _chain()
    improvement_merge = chain.get_revision("0188_self_improvement_merge")
    console_merge = chain.get_revision("0189_console_milestones_merge")
    assert improvement_merge is not None and len(improvement_merge.down_revision) == 8
    assert console_merge is not None and console_merge.down_revision == (
        "0188_self_improvement_merge",
        "0170_generated_media",
    )


# `alembic_version.version_num` is `VARCHAR(32)`, which alembic creates and never
# widens. A longer id is not refused when the file is written or when the chain is
# read - it is refused by the *database*, after the migration's DDL has run, on the
# UPDATE that records the new version. So the schema change lands and the version
# does not, which on a non-transactional step leaves a chain nobody can move.
_VERSION_NUM_LIMIT = 32


def test_no_revision_id_is_too_long_for_the_version_table() -> None:
    too_long = {
        revision.revision: len(revision.revision)
        for revision in _chain().walk_revisions()
        if len(revision.revision) > _VERSION_NUM_LIMIT
    }
    assert not too_long, (
        f"revision ids longer than {_VERSION_NUM_LIMIT} characters: {too_long}. "
        "`alembic_version.version_num` is VARCHAR(32), so such a migration runs "
        "its DDL and then fails writing the version. Shorten the id."
    )
