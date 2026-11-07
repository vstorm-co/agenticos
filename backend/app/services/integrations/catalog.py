"""Products and operations shared by agent tools and workflow steps.

Endpoints are platform code. Neither an agent nor a graph may choose a host or
an HTTP method; this prevents turning an authenticated account into a proxy.
"""

from dataclasses import dataclass
from typing import Literal

type Provider = Literal["google", "microsoft", "slack", "imap"]


@dataclass(frozen=True)
class Operation:
    id: str
    description: str
    method: Literal["GET", "POST", "PATCH", "PUT"]
    url: str
    scopes: tuple[str, ...]
    parameters: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    side_effecting: bool = False
    encoding: Literal["json", "base64", "drive_multipart", "word"] = "json"
    response_format: Literal["json", "file", "word"] = "json"


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    provider: Provider
    operations: tuple[Operation, ...]


PRODUCTS: dict[str, Product] = {
    "gmail": Product(
        "gmail",
        "Gmail",
        "google",
        (
            Operation(
                "search_threads",
                "Search Gmail threads using a Gmail query.",
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/threads",
                (
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                (),
                ("q", "pageToken", "maxResults"),
                False,
            ),
            Operation(
                "read_thread",
                "Read a Gmail thread including its messages.",
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
                (
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                ("thread_id",),
                (),
                False,
            ),
            Operation(
                "read_message",
                "Read a Gmail message.",
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                (
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                ("message_id",),
                (),
                False,
            ),
            Operation(
                "list_labels",
                "List labels in the connected mailbox.",
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/labels",
                (
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                (),
                (),
                False,
            ),
            Operation(
                "create_draft",
                "Create a Gmail draft from a base64url encoded MIME message in message.raw.",
                "POST",
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                (
                    "https://www.googleapis.com/auth/gmail.compose",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                (),
                (),
                True,
            ),
            Operation(
                "send_message",
                "Send a Gmail message with base64url encoded MIME content in raw.",
                "POST",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                (
                    "https://www.googleapis.com/auth/gmail.send",
                    "https://www.googleapis.com/auth/gmail.modify",
                ),
                (),
                (),
                True,
            ),
            Operation(
                "modify_labels",
                "Add or remove labels using addLabelIds and removeLabelIds.",
                "POST",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
                ("https://www.googleapis.com/auth/gmail.modify",),
                ("message_id",),
                (),
                True,
            ),
        ),
    ),
    "google_calendar": Product(
        "google_calendar",
        "Google Calendar",
        "google",
        (
            Operation(
                "list_events",
                "List events in a calendar; use timeMin and timeMax for a time window.",
                "GET",
                "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                (
                    "https://www.googleapis.com/auth/calendar.events.readonly",
                    "https://www.googleapis.com/auth/calendar.readonly",
                    "https://www.googleapis.com/auth/calendar",
                    "https://www.googleapis.com/auth/calendar.events",
                ),
                ("calendar_id",),
                ("q", "timeMin", "timeMax", "pageToken", "maxResults", "singleEvents"),
                False,
            ),
            Operation(
                "free_busy",
                "Check availability using timeMin, timeMax and items with calendar ids.",
                "POST",
                "https://www.googleapis.com/calendar/v3/freeBusy",
                (
                    "https://www.googleapis.com/auth/calendar.freebusy",
                    "https://www.googleapis.com/auth/calendar.readonly",
                    "https://www.googleapis.com/auth/calendar",
                ),
                (),
                (),
                False,
            ),
            Operation(
                "create_event",
                "Create or update an event using a Google Calendar event object.",
                "POST",
                "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                (
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar",
                ),
                ("calendar_id",),
                (),
                True,
            ),
            Operation(
                "update_event",
                "Create or update an event using a Google Calendar event object.",
                "PATCH",
                "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                (
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar",
                ),
                ("calendar_id", "event_id"),
                (),
                True,
            ),
        ),
    ),
    "google_drive": Product(
        "google_drive",
        "Google Drive",
        "google",
        (
            Operation(
                "search_files",
                "Search Drive metadata using the Drive q syntax.",
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                (
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive",
                ),
                (),
                ("q", "pageToken", "pageSize", "fields"),
                False,
            ),
            Operation(
                "file_metadata",
                "Read the metadata of a Drive file.",
                "GET",
                "https://www.googleapis.com/drive/v3/files/{file_id}",
                (
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive",
                ),
                ("file_id",),
                ("fields",),
                False,
            ),
            Operation(
                "copy_file",
                "Copy a Drive file; provide name and parents to create from a template.",
                "POST",
                "https://www.googleapis.com/drive/v3/files/{file_id}/copy",
                (
                    "https://www.googleapis.com/auth/drive",
                    "https://www.googleapis.com/auth/drive.file",
                ),
                ("file_id",),
                (),
                True,
            ),
        ),
    ),
    "google_docs": Product(
        "google_docs",
        "Google Docs",
        "google",
        (
            Operation(
                "read",
                "Read the document structure and content.",
                "GET",
                "https://docs.googleapis.com/v1/documents/{document_id}",
                (
                    "https://www.googleapis.com/auth/documents.readonly",
                    "https://www.googleapis.com/auth/documents",
                ),
                ("document_id",),
                (),
                False,
            ),
            Operation(
                "create",
                "Create a new document using its title or properties.",
                "POST",
                "https://docs.googleapis.com/v1/documents",
                ("https://www.googleapis.com/auth/documents",),
                (),
                (),
                True,
            ),
            Operation(
                "batch_update",
                "Apply the product API requests array to a document.",
                "POST",
                "https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate",
                ("https://www.googleapis.com/auth/documents",),
                ("document_id",),
                (),
                True,
            ),
        ),
    ),
    "google_sheets": Product(
        "google_sheets",
        "Google Sheets",
        "google",
        (
            Operation(
                "read",
                "Read the document structure and content.",
                "GET",
                "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
                (
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/spreadsheets",
                ),
                ("spreadsheet_id",),
                (),
                False,
            ),
            Operation(
                "create",
                "Create a new document using its title or properties.",
                "POST",
                "https://sheets.googleapis.com/v4/spreadsheets",
                ("https://www.googleapis.com/auth/spreadsheets",),
                (),
                (),
                True,
            ),
            Operation(
                "batch_update",
                "Apply the product API requests array to a document.",
                "POST",
                "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
                ("https://www.googleapis.com/auth/spreadsheets",),
                ("spreadsheet_id",),
                (),
                True,
            ),
            Operation(
                "read_range",
                "Read a spreadsheet range in A1 notation.",
                "GET",
                "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}",
                (
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/spreadsheets",
                ),
                ("spreadsheet_id", "range"),
                ("valueRenderOption",),
                False,
            ),
            Operation(
                "append_rows",
                "Append a values array to a spreadsheet range.",
                "POST",
                "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}:append",
                ("https://www.googleapis.com/auth/spreadsheets",),
                ("spreadsheet_id", "range"),
                ("valueInputOption", "insertDataOption"),
                True,
            ),
            Operation(
                "update_cells",
                "Update cells with a values array.",
                "PUT",
                "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range}",
                ("https://www.googleapis.com/auth/spreadsheets",),
                ("spreadsheet_id", "range"),
                ("valueInputOption",),
                True,
            ),
        ),
    ),
    "google_slides": Product(
        "google_slides",
        "Google Slides",
        "google",
        (
            Operation(
                "read",
                "Read the document structure and content.",
                "GET",
                "https://slides.googleapis.com/v1/presentations/{presentation_id}",
                (
                    "https://www.googleapis.com/auth/presentations.readonly",
                    "https://www.googleapis.com/auth/presentations",
                ),
                ("presentation_id",),
                (),
                False,
            ),
            Operation(
                "create",
                "Create a new document using its title or properties.",
                "POST",
                "https://slides.googleapis.com/v1/presentations",
                ("https://www.googleapis.com/auth/presentations",),
                (),
                (),
                True,
            ),
            Operation(
                "batch_update",
                "Apply the product API requests array to a document.",
                "POST",
                "https://slides.googleapis.com/v1/presentations/{presentation_id}:batchUpdate",
                ("https://www.googleapis.com/auth/presentations",),
                ("presentation_id",),
                (),
                True,
            ),
        ),
    ),
    "outlook_mail": Product(
        "outlook_mail",
        "Outlook mail",
        "microsoft",
        (
            Operation(
                "search_messages",
                "Search Outlook messages using Graph search syntax.",
                "GET",
                "https://graph.microsoft.com/v1.0/me/messages",
                ("Mail.Read", "Mail.ReadWrite"),
                (),
                ("$search", "$filter", "$top", "$skip"),
                False,
            ),
            Operation(
                "read_message",
                "Read an Outlook message.",
                "GET",
                "https://graph.microsoft.com/v1.0/me/messages/{message_id}",
                ("Mail.Read", "Mail.ReadWrite"),
                ("message_id",),
                (),
                False,
            ),
            Operation(
                "create_draft",
                "Create an Outlook draft using subject, body and recipients.",
                "POST",
                "https://graph.microsoft.com/v1.0/me/messages",
                ("Mail.ReadWrite",),
                (),
                (),
                True,
            ),
            Operation(
                "send_mail",
                "Send Outlook mail using a message object.",
                "POST",
                "https://graph.microsoft.com/v1.0/me/sendMail",
                ("Mail.Send",),
                (),
                (),
                True,
            ),
        ),
    ),
    "outlook_calendar": Product(
        "outlook_calendar",
        "Outlook Calendar",
        "microsoft",
        (
            Operation(
                "list_events",
                "List events in the connected Outlook calendar.",
                "GET",
                "https://graph.microsoft.com/v1.0/me/events",
                ("Calendars.Read", "Calendars.ReadWrite"),
                (),
                ("$filter", "$top", "$select"),
                False,
            ),
            Operation(
                "free_busy",
                "Read availability using schedules, startTime and endTime.",
                "POST",
                "https://graph.microsoft.com/v1.0/me/calendar/getSchedule",
                ("Calendars.Read", "Calendars.ReadWrite"),
                (),
                (),
                False,
            ),
            Operation(
                "create_event",
                "Create or update an Outlook event.",
                "POST",
                "https://graph.microsoft.com/v1.0/me/events",
                ("Calendars.ReadWrite",),
                (),
                (),
                True,
            ),
            Operation(
                "update_event",
                "Create or update an Outlook event.",
                "PATCH",
                "https://graph.microsoft.com/v1.0/me/events/{event_id}",
                ("Calendars.ReadWrite",),
                ("event_id",),
                (),
                True,
            ),
        ),
    ),
    "microsoft_files": Product(
        "microsoft_files",
        "OneDrive / SharePoint",
        "microsoft",
        (
            Operation(
                "read_metadata",
                "Read a OneDrive or SharePoint item by drive and item id.",
                "GET",
                "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}",
                ("Files.Read", "Files.Read.All", "Files.ReadWrite", "Files.ReadWrite.All"),
                ("drive_id", "item_id"),
                (),
                False,
            ),
            Operation(
                "list_children",
                "List items in a OneDrive or SharePoint folder.",
                "GET",
                "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/children",
                ("Files.Read", "Files.Read.All", "Files.ReadWrite", "Files.ReadWrite.All"),
                ("drive_id", "item_id"),
                ("$top",),
                False,
            ),
            Operation(
                "search_files",
                "Search files within a drive.",
                "GET",
                "https://graph.microsoft.com/v1.0/drives/{drive_id}/root/search(q='{search}')",
                ("Files.Read", "Files.Read.All", "Files.ReadWrite", "Files.ReadWrite.All"),
                ("drive_id", "search"),
                (),
                False,
            ),
        ),
    ),
    "excel": Product(
        "excel",
        "Excel",
        "microsoft",
        (
            Operation(
                "list_sheets",
                "List worksheets in an Excel workbook.",
                "GET",
                "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/workbook/worksheets",
                ("Files.ReadWrite",),
                ("drive_id", "item_id"),
                (),
                False,
            ),
            Operation(
                "append_rows",
                "Append rows using a values array to an Excel table.",
                "POST",
                "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/workbook/tables/{table_id}/rows/add",
                ("Files.ReadWrite",),
                ("drive_id", "item_id", "table_id"),
                (),
                True,
            ),
        ),
    ),
    "teams": Product(
        "teams",
        "Teams",
        "microsoft",
        (
            Operation(
                "list_chats",
                "List chats of the connected Microsoft account.",
                "GET",
                "https://graph.microsoft.com/v1.0/me/chats",
                ("Chat.Read", "Chat.ReadWrite"),
                (),
                ("$top",),
                False,
            ),
            Operation(
                "read_messages",
                "Read messages in a Teams chat.",
                "GET",
                "https://graph.microsoft.com/v1.0/chats/{chat_id}/messages",
                ("Chat.Read", "Chat.ReadWrite"),
                ("chat_id",),
                ("$top",),
                False,
            ),
            Operation(
                "read_channel",
                "Read messages in a Teams channel.",
                "GET",
                "https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages",
                ("ChannelMessage.Read.All",),
                ("team_id", "channel_id"),
                ("$top",),
                False,
            ),
            Operation(
                "post_message",
                "Post a Teams chat message with a body object.",
                "POST",
                "https://graph.microsoft.com/v1.0/chats/{chat_id}/messages",
                ("ChatMessage.Send", "Chat.ReadWrite"),
                ("chat_id",),
                (),
                True,
            ),
            Operation(
                "post_channel",
                "Post a Teams channel message with a body object.",
                "POST",
                "https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages",
                ("ChannelMessage.Send",),
                ("team_id", "channel_id"),
                (),
                True,
            ),
        ),
    ),
    "slack": Product(
        "slack",
        "Slack",
        "slack",
        (
            Operation(
                "my_mentions",
                "Search mentions of the connected Slack user.",
                "GET",
                "https://slack.com/api/search.messages",
                ("search:read",),
                query=("count", "page"),
            ),
            Operation(
                "search_messages",
                "Search Slack messages using a Slack query.",
                "GET",
                "https://slack.com/api/search.all",
                ("search:read",),
                (),
                ("query", "count", "page"),
                False,
            ),
            Operation(
                "read_history",
                "Read a Slack conversation.",
                "GET",
                "https://slack.com/api/conversations.history",
                ("channels:history", "groups:history", "im:history", "mpim:history"),
                (),
                ("channel", "oldest", "cursor", "limit"),
                False,
            ),
            Operation(
                "read_thread",
                "Read replies to a Slack message.",
                "GET",
                "https://slack.com/api/conversations.replies",
                ("channels:history", "groups:history", "im:history", "mpim:history"),
                (),
                ("channel", "ts", "cursor", "limit"),
                False,
            ),
            Operation(
                "list_channels",
                "List accessible Slack conversations.",
                "GET",
                "https://slack.com/api/conversations.list",
                ("channels:read", "groups:read", "im:read", "mpim:read"),
                (),
                ("types", "cursor", "limit"),
                False,
            ),
            Operation(
                "list_users",
                "List Slack users.",
                "GET",
                "https://slack.com/api/users.list",
                ("users:read",),
                (),
                ("cursor", "limit"),
                False,
            ),
            Operation(
                "lookup_user",
                "Look up a Slack user by email.",
                "GET",
                "https://slack.com/api/users.lookupByEmail",
                ("users:read.email",),
                (),
                ("email",),
                False,
            ),
            Operation(
                "post_message",
                "Post or reply in a Slack conversation using channel, text and optional thread_ts.",
                "POST",
                "https://slack.com/api/chat.postMessage",
                ("chat:write",),
                (),
                (),
                True,
            ),
            Operation(
                "open_dm",
                "Open a Slack direct message conversation using users.",
                "POST",
                "https://slack.com/api/conversations.open",
                ("im:write",),
                (),
                (),
                True,
            ),
            Operation(
                "react",
                "Add a reaction using channel, timestamp and name.",
                "POST",
                "https://slack.com/api/reactions.add",
                ("reactions:write",),
                (),
                (),
                True,
            ),
        ),
    ),
    "imap_mail": Product(
        "imap_mail",
        "IMAP mail",
        "imap",
        (
            Operation(
                "search_messages",
                "Search the connected IMAP mailbox using IMAP search syntax.",
                "GET",
                "",
                ("mail:read",),
                query=("query",),
            ),
            Operation(
                "read_message",
                "Read one IMAP message by UID without marking it as read.",
                "GET",
                "",
                ("mail:read",),
                parameters=("message_id",),
            ),
        ),
    ),
}


PRODUCTS["google_drive"] = Product(
    "google_drive",
    "Google Drive",
    "google",
    (
        *PRODUCTS["google_drive"].operations,
        Operation(
            "read_file",
            "Read a Drive text, PDF or Word file, up to 20 MB and 100000 output characters.",
            "GET",
            "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            (
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/drive",
            ),
            parameters=("file_id",),
            response_format="file",
        ),
        Operation(
            "upload_file",
            "Upload a file with content_base64, name, content_type and optional parent_id.",
            "POST",
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            ("https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"),
            side_effecting=True,
            encoding="drive_multipart",
        ),
    ),
)
PRODUCTS["microsoft_files"] = Product(
    "microsoft_files",
    "OneDrive / SharePoint",
    "microsoft",
    (
        *PRODUCTS["microsoft_files"].operations,
        Operation(
            "read_file",
            "Read a OneDrive or SharePoint text, PDF or Word file up to 20 MB.",
            "GET",
            "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content",
            ("Files.Read", "Files.Read.All", "Files.ReadWrite", "Files.ReadWrite.All"),
            parameters=("drive_id", "item_id"),
            response_format="file",
        ),
        Operation(
            "upload_file",
            "Create or replace a file in a folder using content_base64 and content_type.",
            "PUT",
            "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{parent_id}:/{filename}:/content",
            ("Files.ReadWrite", "Files.ReadWrite.All"),
            parameters=("drive_id", "parent_id", "filename"),
            side_effecting=True,
            encoding="base64",
        ),
    ),
)
PRODUCTS["word"] = Product(
    "word",
    "Word",
    "microsoft",
    (
        Operation(
            "read_document",
            "Read the text of a Word document in OneDrive or SharePoint.",
            "GET",
            "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content",
            ("Files.Read", "Files.Read.All", "Files.ReadWrite", "Files.ReadWrite.All"),
            parameters=("drive_id", "item_id"),
            response_format="word",
        ),
        Operation(
            "write_document",
            "Create or replace a Word document using title and paragraphs. The filename must end in .docx.",
            "PUT",
            "https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{parent_id}:/{filename}:/content",
            ("Files.ReadWrite", "Files.ReadWrite.All"),
            parameters=("drive_id", "parent_id", "filename"),
            side_effecting=True,
            encoding="word",
        ),
    ),
)


def application_scopes(product_id: str, operation: Operation) -> tuple[str, ...]:
    """Application permissions where Graph supports the actual operation."""
    if product_id in {"outlook_mail", "outlook_calendar"}:
        return operation.scopes
    if product_id in {"microsoft_files", "word"}:
        return (
            ("Files.ReadWrite.All", "Sites.Selected")
            if operation.side_effecting
            else ("Files.Read.All", "Sites.Read.All", "Sites.Selected", "Files.ReadWrite.All")
        )
    if product_id == "teams":
        return {
            "list_chats": ("Chat.ReadBasic.All", "Chat.Read.All", "Chat.ReadWrite.All"),
            "read_messages": ("Chat.Read.All", "Chat.ReadWrite.All"),
            "read_channel": ("ChannelMessage.Read.All",),
        }.get(operation.id, ())
    return ()
