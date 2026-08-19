# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import TypedDict

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api.exception_handlers import register_exception_handlers
from app.api.router import api_router
from app.agents.capabilities import load_builtins
from app.agents.capabilities.knowledge import aclose_retrieval_service
from app.core.config import settings
from app.db.session import close_db, get_db_context
from app.core.logfire_setup import instrument_app, setup_logfire
from app.core.logfire_setup import instrument_asyncpg
from app.core.logfire_setup import instrument_redis
from app.core.logfire_setup import instrument_httpx
from app.core.logfire_setup import instrument_pydantic_ai
from app.core.logging import setup_logging
from app.core.body_limit import BodySizeLimitMiddleware
from app.core import maintenance
from app.core.maintenance import MaintenanceModeMiddleware
from app.core.middleware import RequestIDMiddleware
from app.core.watchdog import EventLoopWatchdog
from app.clients.redis import RedisClient
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vectorstore import PgVectorStore
from app.services.embedding_resolution import embeddings_for_collection
from app.services.rag.vectorstore import BaseVectorStore
from app.repositories.channel_bot import get_active_polling_bots
from app.services.channel_bot import unseal_bot_token, unseal_slack_app_token
from app.services.channels import register_adapter
from app.services import rate_limit
from app.services.channels import dedupe as channel_dedupe
from app.services.channels import membership as channel_membership
from app.services.channels.supervisor import open_inbound_stream

logger = logging.getLogger(__name__)


class LifespanState(TypedDict, total=False):
    """Lifespan state - resources available via request.state."""

    redis: RedisClient
    embedding_service: EmbeddingService
    vector_store: BaseVectorStore


async def _start_channel_polling(channel: str) -> None:
    """Open a stream for every active polling bot on this platform.

    The catch-up pass, and only that. A bot registered *while* the process is
    running has its stream opened by `ChannelBotService`, through the same
    `open_inbound_stream` - which is why the sequence lives there rather than
    here. Two copies of "tell the adapter the server address, then connect"
    is one copy that will be missing a step.

    """
    async with get_db_context() as _db:
        _bots = await get_active_polling_bots(_db, channel)
    for _bot in _bots:
        await open_inbound_stream(
            bot_id=str(_bot.id),
            platform=channel,
            token=unseal_bot_token(_bot),
            api_base_url=_bot.api_base_url,
            app_token=unseal_slack_app_token(_bot),
        )
    logger.info("%s: polling started for %d bot(s)", channel.capitalize(), len(_bots))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[LifespanState, None]:
    """Application lifespan - startup and shutdown events.

    Resources yielded here are available via request.state in route handlers.
    See: https://asgi.readthedocs.io/en/latest/specs/lifespan.html#lifespan-state
    """
    state: LifespanState = {}
    watchdog = EventLoopWatchdog(wedged_after=settings.EVENT_LOOP_WEDGED_AFTER)
    setup_logfire()
    # Capability modules register themselves on import; nothing the Builder can
    # offer exists until this has run.
    load_builtins()
    instrument_asyncpg()
    instrument_redis()
    instrument_httpx()
    instrument_pydantic_ai()
    redis_client = RedisClient()
    await redis_client.connect()
    state["redis"] = redis_client
    # The channel router runs outside any request - webhook background tasks
    # and the polling loops alike - so the dedupe claim cannot reach Redis
    # through request.state; it is handed the shared client here instead.
    channel_dedupe.configure(redis_client)
    # And the rate limits, for the same reason: the widget's socket is admitted
    # outside any request the limiter could read `request.state` from, and a
    # count kept in this process would be off by the worker count (#39).
    rate_limit.configure(redis_client)
    # And the membership check behind the participant model, which the
    # conversation service consults from inside a request but caches in the
    # Redis every worker shares (#641).
    channel_membership.configure(redis_client)
    # And the maintenance gate, which runs above the dependency graph on every
    # request and so has no `request.state` to read either.
    maintenance.configure(redis_client)
    embedder: EmbeddingService | None = None
    try:
        embedder = EmbeddingService(settings=settings.rag)
        embedder.warmup()
        state["embedding_service"] = embedder
    except Exception as e:
        logger.error("Embedding service warmup failed: %s. RAG will not be available.", e)
    if embedder is not None:
        try:
            vector_store = PgVectorStore(
                settings=settings.rag,
                embedding_service=embedder,
                resolver=embeddings_for_collection,
            )
            state["vector_store"] = vector_store
        except Exception as e:
            logger.error("pgvector connection failed: %s. Vector store will not be available.", e)

    # Imported here rather than at module top so that importing `app.main` does
    # not pull in the channel SDKs (aiogram, the Slack client) - ~1.2s of import
    # that the API and the test suite pay for on every process start and never
    # use. The adapters are only ever needed from this point on: registered at
    # startup, and stopped after the yield below (#520).
    from app.services.channels.mattermost import MattermostAdapter
    from app.services.channels.slack import SlackAdapter
    from app.services.channels.telegram import TelegramAdapter

    _telegram_adapter = TelegramAdapter()
    register_adapter(_telegram_adapter)
    try:
        await _start_channel_polling("telegram")
    except (OSError, ValueError, RuntimeError) as _exc:
        logger.error("Telegram: failed to start polling: %s", _exc)

    _mattermost_adapter = MattermostAdapter()
    register_adapter(_mattermost_adapter)
    try:
        await _start_channel_polling("mattermost")
    except (OSError, ValueError, RuntimeError) as _mm_exc:
        logger.error("Mattermost: failed to start the event stream: %s", _mm_exc)

    _slack_adapter = SlackAdapter()
    register_adapter(_slack_adapter)
    try:
        await _start_channel_polling("slack")
    except (OSError, ValueError, RuntimeError) as _slack_exc:
        logger.error("Slack: failed to start Socket Mode: %s", _slack_exc)

    # Started once startup is done and stopped only at the very end, so it
    # covers serving and shutdown: a worker whose event loop stops turning is
    # invisible to every other recovery path this deployment has, and it kills
    # its own process, which each stack's supervisor - or Docker's restart
    # policy on the dev stack - already replaces. Startup is deliberately not
    # watched; app/core/watchdog.py says why.
    watchdog.start()
    yield state
    # The channel consumers stop first, and the stores go after them. Serving is
    # already drained by the time this runs, but a polling task is work this
    # process owns: an inbound Telegram or Slack message can start a run, and a
    # run can search, so disposing a store while one is still turning both races
    # a search in flight and lets the next one build a replacement pool that
    # nothing is left to close.
    for _bid in list(_telegram_adapter._polling_tasks.keys()):
        await _telegram_adapter.stop_polling(_bid)
    for _sbid in list(_slack_adapter._socket_tasks.keys()):
        await _slack_adapter.stop_polling(_sbid)
    for _mbid in list(_mattermost_adapter._socket_tasks.keys()):
        await _mattermost_adapter.stop_polling(_mbid)
    if "vector_store" in state:
        with suppress(Exception):
            await state["vector_store"].aclose()
    # The knowledge capability holds a store of its own, built on the first
    # search and reachable from no request, so the line above never saw it (#948).
    with suppress(Exception):
        await aclose_retrieval_service()
    channel_dedupe.configure(None)
    rate_limit.configure(None)
    channel_membership.configure(None)
    maintenance.configure(None)
    if "redis" in state:
        await state["redis"].close()

    await close_db()
    watchdog.stop()


SHOW_DOCS_ENVIRONMENTS = ("local", "staging", "development")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    show_docs = settings.ENVIRONMENT in SHOW_DOCS_ENVIRONMENTS
    openapi_url = f"{settings.API_V1_STR}/openapi.json" if show_docs else None
    docs_url = "/docs" if show_docs else None
    redoc_url = "/redoc" if show_docs else None

    openapi_tags = [
        {
            "name": "health",
            "description": "Health check endpoints for monitoring and Kubernetes probes",
        },
        {
            "name": "auth",
            "description": "Authentication endpoints - login, register, token refresh",
        },
        {
            "name": "users",
            "description": "User management endpoints",
        },
        {
            "name": "oauth",
            "description": "OAuth2 social login endpoints (Google, etc.)",
        },
        {
            "name": "sessions",
            "description": "Session management - view and manage active login sessions",
        },
        {
            "name": "conversations",
            "description": "AI conversation persistence - manage chat history",
        },
        {
            "name": "agent",
            "description": "AI agent WebSocket endpoint for real-time chat",
        },
        {
            "name": "rag",
            "description": "Retrieval Augmented Generation endpoints",
        },
    ]

    setup_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        summary="FastAPI application with Logfire observability",
        description="""
OS for your agents.

## Features
- **Authentication**: JWT-based authentication with refresh tokens
- **API Key**: Header-based API key authentication
- **Database**: Async database operations
- **Redis**: Caching and session storage
- **Rate Limiting**: Request rate limiting per client
- **AI Agent**: PydanticAI-powered conversational assistant
- **Observability**: Logfire integration for tracing and monitoring
- **RAG**: Retrieval Augmented Generation over pgvector

## Documentation

- [Swagger UI](/docs) - Interactive API documentation
- [ReDoc](/redoc) - Alternative documentation view
        """.strip(),
        # `app.__version__`, which reads the installed distribution. The number
        # in `/docs` and `/openapi.json` is the one a client integrates against,
        # and it used to be a literal that disagreed with `pyproject.toml`.
        version=__version__,
        openapi_url=openapi_url,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_tags=openapi_tags,
        contact={
            "name": "DEENUU1",
            "email": "kacper.wlodarczyk@vstorm.co",
        },
        license_info={
            "name": "MIT",
            "identifier": "MIT",
        },
        lifespan=lifespan,
    )
    # setup_logfire() is also called from the lifespan for the runtime app, but
    # we call it here too so that import-time test clients (which never run
    # lifespan) silence the "configure first" warning. setup_logfire() is
    # idempotent via a module-level guard in logfire_setup.py.
    setup_logfire()
    instrument_app(app)

    # Outermost of the three, because it exists to answer before anything reads the
    # body - a middleware under CORS or the session would run after the request had
    # already been received.
    app.add_middleware(BodySizeLimitMiddleware)

    # Under the body limit and above everything else: a refused request should
    # still be refused for being too large first, and a window that is open has
    # to close the routes rather than the layers around them.
    app.add_middleware(MaintenanceModeMiddleware)

    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
    )

    app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


app = create_app()
