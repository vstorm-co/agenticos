"""The network pool launches one isolated node for an explicitly admitted request."""

from app.services.network_connections import NetworkConnectionService
from app.worker.jobs import RunNetworkConnection


async def run_connection(job: RunNetworkConnection) -> None:
    await NetworkConnectionService.run_node(job)


async def settle_connection(job: RunNetworkConnection, why: str) -> None:
    await NetworkConnectionService.settle_ended(job, why)


async def sweep_connections() -> int:
    return await NetworkConnectionService.recover()
