"""A revision id has to fit the column Alembic records it in.

`alembic_version.version_num` is `varchar(32)`. A longer id passes every check
that does not run the chain against a real database, then fails the upgrade
that writes it with `StringDataRightTruncation` (#225's first CI run).
"""

from alembic.config import Config
from alembic.script import ScriptDirectory

_VERSION_NUM_LENGTH = 32


def test_every_revision_id_fits_alembics_version_column() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    too_long = sorted(
        revision.revision
        for revision in script.walk_revisions()
        if len(revision.revision) > _VERSION_NUM_LENGTH
    )

    assert too_long == []
