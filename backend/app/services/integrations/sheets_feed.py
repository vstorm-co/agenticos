"""New appended Sheets rows: establish a quiet tail, then read only the next window."""

import json
from urllib.parse import quote

from pydantic import JsonValue, SecretStr

from app.core.exceptions import ExternalServiceError
from app.services.integrations import client
from app.services.integrations.catalog import Operation
from app.services.integrations.feeds import Change, Changes


def sheet_key(spreadsheet_id: str, sheet_name: str) -> str:
    return json.dumps([spreadsheet_id, sheet_name], separators=(",", ":"))


async def rows_since(
    token: SecretStr, cursor: dict[str, JsonValue] | None, *, spreadsheet_id: str, sheet_name: str
) -> Changes:
    previous = (cursor or {}).get("last_row")
    baseline = not isinstance(previous, int) or previous < 0
    sheet = "'" + sheet_name.replace("'", "''") + "'"
    selected = f"{sheet}!A:ZZ" if baseline else f"{sheet}!A{previous + 1}:ZZ{previous + 100}"
    operation = Operation(
        "sheet_changes",
        "Read appended spreadsheet rows",
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id, safe='')}/values/{quote(selected, safe='')}",
        (),
    )
    result = await client.execute(operation, token, parameters={}, query={}, body=None)
    values = result.get("values", [])
    if not isinstance(values, list):
        raise ExternalServiceError(message="Google Sheets did not return rows")
    if baseline:
        return Changes(cursor={"last_row": len(values)})
    assert isinstance(previous, int)
    return Changes(
        events=[
            Change(
                id=f"sheet:{spreadsheet_id}:{sheet_name}:{previous + index + 1}",
                payload={
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_name": sheet_name,
                    "row": previous + index + 1,
                    "values": row,
                },
            )
            for index, row in enumerate(values)
        ],
        cursor={"last_row": previous + len(values)},
    )
