# knowledge.add

Adds a bound text (with a `title`) or a run file to one to five knowledge
collections, through the same upload the console's collection page uses: the
collection's own parsing and chunking settings, the organization's budget
check, and ingestion queued rather than waited for. The output names each
collection's document and its status.

A text is ingested as `<title>.md`. A document of the same name is replaced
rather than duplicated, so a retry or a second run updates it. Publishing - and
every run - refuses a collection the principal may not add to.
