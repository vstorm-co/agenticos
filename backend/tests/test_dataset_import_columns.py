"""The import dialog lists the columns the importer reads, in its order.

The console describes a dataset file before the file picker opens, and its
template download writes one header row. Both come from `IMPORT_COLUMNS` in
`frontend/src/components/datasets/import-columns.ts`, a copy of
:data:`COLUMNS` - so a column added here and not there is one nobody is told
about, and a column dropped here is a template the importer refuses. This reads
the list the frontend ships and compares it with the importer's, order included.
"""

import re
from pathlib import Path

from app.services.dataset_files import COLUMNS

COLUMNS_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "components"
    / "datasets"
    / "import-columns.ts"
)


def test_the_import_dialog_lists_the_importer_s_columns_in_order() -> None:
    source = COLUMNS_PATH.read_text(encoding="utf-8")
    match = re.search(r"export const IMPORT_COLUMNS = \[(.*?)\] as const;", source, re.DOTALL)
    assert match, f"could not find `export const IMPORT_COLUMNS` in {COLUMNS_PATH.name}"

    assert tuple(re.findall(r'"([^"]+)"', match.group(1))) == COLUMNS
