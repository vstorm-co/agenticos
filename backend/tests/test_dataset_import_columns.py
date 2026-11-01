"""The import dialog lists the columns the importer reads, in its order.

The console describes a dataset file before the file picker opens, and its
template download writes a file with every column and one case. Both come
from `IMPORT_COLUMNS` in `frontend/src/components/datasets/import-columns.ts`,
a copy of
:data:`COLUMNS` - so a column added here and not there is one nobody is told
about, and a column dropped here is a template the importer refuses. This reads
the list the frontend ships and compares it with the importer's, order included,
and imports the template the console downloads.
"""

import re
from pathlib import Path

from app.services.dataset_files import COLUMNS, parse

DATASETS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "datasets"
COLUMNS_PATH = DATASETS / "import-columns.ts"
# Written by the console's `importTemplate`, which its own test holds equal to this file.
TEMPLATE_PATH = DATASETS / "import-template.fixture.csv"


def test_the_import_dialog_lists_the_importer_s_columns_in_order() -> None:
    source = COLUMNS_PATH.read_text(encoding="utf-8")
    match = re.search(r"export const IMPORT_COLUMNS = \[(.*?)\] as const;", source, re.DOTALL)
    assert match, f"could not find `export const IMPORT_COLUMNS` in {COLUMNS_PATH.name}"

    assert tuple(re.findall(r'"([^"]+)"', match.group(1))) == COLUMNS


def test_the_console_s_template_imports_as_one_case() -> None:
    (case,) = parse(TEMPLATE_PATH.read_bytes(), "csv")

    assert case.input == "How long does a refund take?"
    assert case.tags == ["refunds", "billing"]
    assert case.checks[0].type == "contains"
