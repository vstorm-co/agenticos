"""Queue adapters keep the same transfer service as the HTTP review flow."""

from app.db.session import get_worker_db_context
from app.services.portability import PortableTransferService
from app.worker.attempt import current_attempt_number
from app.worker.jobs import PortableTransferPayload


async def portable_transfer(payload: PortableTransferPayload) -> None:
    attempt = current_attempt_number()
    async with get_worker_db_context() as db:
        claimed = await PortableTransferService(db).claim(payload, attempt=attempt)
    if claimed:
        async with get_worker_db_context() as db:
            await PortableTransferService(db).run(payload, attempt=attempt)


async def settle_transfer(payload: PortableTransferPayload, _why: str) -> None:
    async with get_worker_db_context() as db:
        await PortableTransferService(db).settle(payload)


async def sweep_transfers() -> None:
    async with get_worker_db_context() as db:
        await PortableTransferService(db).sweep()
