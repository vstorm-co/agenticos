# Release Notes

Every notable change to AgenticOS, newest first. This page *is*
[`CHANGELOG.md`](https://github.com/vstorm-co/agenticos/blob/main/CHANGELOG.md)
from the repository — read at build time rather than copied, so the file and the
page cannot drift apart.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things are versioned separately from the list below.

!!! info "`SPEC_VERSION`"

    The agent spec format. A published agent and a client's exported YAML both
    carry it, so it only ever moves forward with a migration that keeps old
    documents loading. See [the spec reference](reference/spec.md).

!!! info "The migration chain"

    `backend/alembic/versions/`, squashed to a single `0001_baseline`. Revision
    ids named below describe *when* something changed, not a file that still
    exists — schema changes are listed by what they do.

<div class="agenticos-release-notes" markdown>

<!-- changelog -->

</div>
