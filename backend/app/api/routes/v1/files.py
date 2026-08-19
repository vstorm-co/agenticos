"""File upload and download endpoints for chat attachments."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, FileUploadSvc
from app.api.routes.v1._chat_file_bytes import chat_file_response
from app.core.exceptions import NotFoundError
from app.schemas.file import FileInfo, FileUploadResponse
from app.services.file_upload import make_preview

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload a file for use in chat."""
    data = await file.read()
    chat_file = await file_upload_svc.upload(
        user_id=current_user.id,
        file_data=data,
        filename=file.filename or "unknown",
        content_type=file.content_type,
    )
    return FileUploadResponse(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
        preview=make_preview(chat_file.parsed_content),
    )


@router.get("/{file_id}", response_model=None)
async def download_file(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    disposition: str = "inline",
) -> Any:
    """Serve a file. Only the owner can access their files.

    By default the response is `Content-Disposition: inline` so PDFs, images
    and audio/video render directly inside an `<iframe>` / media tag (used
    by the chat file-preview panel). Pass `?disposition=attachment` to force
    the browser's download dialog (used by the explicit "Download" button).
    """
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        ) from None

    return chat_file_response(file_upload_svc, chat_file, disposition=disposition)


@router.get("/{file_id}/info", response_model=FileInfo)
async def get_file_info(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> Any:
    """Get file metadata. Only the owner can access."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        ) from None

    return FileInfo(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
        preview=make_preview(chat_file.parsed_content),
        created_at=chat_file.created_at,
        user_id=chat_file.user_id,
    )
