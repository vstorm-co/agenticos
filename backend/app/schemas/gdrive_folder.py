"""Google Drive folders the sync-source setup can browse."""

from pydantic import BaseModel


class GoogleDrivePickerItem(BaseModel):
    id: str
    name: str


class GoogleDriveFolderPickerResponse(BaseModel):
    drives: list[GoogleDrivePickerItem]
    folders: list[GoogleDrivePickerItem]
