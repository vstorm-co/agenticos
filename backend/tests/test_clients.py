"""Tests for client modules."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.redis import RedisClient


class TestRedisClient:
    """Tests for RedisClient."""

    @pytest.fixture
    def redis_client(self) -> RedisClient:
        """Create a RedisClient instance."""
        return RedisClient(url="redis://localhost:6379")

    @pytest.fixture
    def mock_aioredis(self) -> MagicMock:
        """Create a mock aioredis client."""
        mock = MagicMock()
        mock.get = AsyncMock(return_value="value")
        mock.set = AsyncMock()
        mock.delete = AsyncMock(return_value=1)
        mock.exists = AsyncMock(return_value=1)
        mock.ping = AsyncMock()
        mock.close = AsyncMock()
        return mock

    @pytest.mark.anyio
    async def test_connect(self, redis_client: RedisClient):
        """Test Redis connection."""
        with patch("app.clients.redis.aioredis") as mock_aioredis:
            mock_client = MagicMock()
            mock_aioredis.from_url.return_value = mock_client

            await redis_client.connect()

            assert redis_client.client is not None
            mock_aioredis.from_url.assert_called_once()

    @pytest.mark.anyio
    async def test_close(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test closing Redis connection."""
        redis_client.client = mock_aioredis

        await redis_client.close()

        mock_aioredis.close.assert_called_once()
        assert redis_client.client is None

    @pytest.mark.anyio
    async def test_close_when_not_connected(self, redis_client: RedisClient):
        """Test closing when not connected does nothing."""
        redis_client.client = None

        await redis_client.close()  # Should not raise

    @pytest.mark.anyio
    async def test_get(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test getting a value."""
        redis_client.client = mock_aioredis

        result = await redis_client.get("test_key")

        assert result == "value"
        mock_aioredis.get.assert_called_once_with("test_key")

    @pytest.mark.anyio
    async def test_get_not_connected(self, redis_client: RedisClient):
        """Test getting when not connected raises error."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.get("test_key")

    @pytest.mark.anyio
    async def test_set(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test setting a value."""
        redis_client.client = mock_aioredis

        await redis_client.set("test_key", "test_value")

        mock_aioredis.set.assert_called_once_with("test_key", "test_value", ex=None, nx=False)

    @pytest.mark.anyio
    async def test_set_with_ttl(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test setting a value with TTL."""
        redis_client.client = mock_aioredis

        await redis_client.set("test_key", "test_value", ttl=60)

        mock_aioredis.set.assert_called_once_with("test_key", "test_value", ex=60, nx=False)

    @pytest.mark.anyio
    async def test_set_nx_reports_who_won(
        self, redis_client: RedisClient, mock_aioredis: MagicMock
    ):
        """SET NX answers True to the caller that wrote the key and False to
        the one Redis refused - the nil reply the driver surfaces as None."""
        redis_client.client = mock_aioredis

        mock_aioredis.set.return_value = True
        assert await redis_client.set("test_key", "1", ttl=60, nx=True) is True

        mock_aioredis.set.return_value = None
        assert await redis_client.set("test_key", "1", ttl=60, nx=True) is False

        mock_aioredis.set.assert_called_with("test_key", "1", ex=60, nx=True)

    @pytest.mark.anyio
    async def test_set_not_connected(self, redis_client: RedisClient):
        """Test setting when not connected raises error."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.set("test_key", "test_value")

    @pytest.mark.anyio
    async def test_count_in_window_increments_and_sets_a_deadline_only_once(
        self, redis_client: RedisClient, mock_aioredis: MagicMock
    ):
        """`EXPIRE … NX` is what makes the window fixed rather than sliding.

        A plain `EXPIRE` on every hit pushes the deadline out with each call, so a
        caller who never stops never resets and their allowance is gone until they
        do - the opposite of what a per-minute limit means.
        """
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=[3, True])
        mock_aioredis.pipeline = MagicMock(return_value=pipeline)
        redis_client.client = mock_aioredis

        used = await redis_client.count_in_window("ratelimit:s:c", ttl=60)

        assert used == 3
        pipeline.incr.assert_called_once_with("ratelimit:s:c")
        pipeline.expire.assert_called_once_with("ratelimit:s:c", 60, nx=True)

    @pytest.mark.anyio
    async def test_count_in_window_not_connected(self, redis_client: RedisClient):
        """Refused rather than counted into nothing: a limiter that silently
        counts nowhere is a limit that reads as holding."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.count_in_window("k", ttl=60)

    @pytest.mark.anyio
    async def test_a_lease_is_extended_and_given_back_only_by_its_holder(
        self, redis_client: RedisClient, mock_aioredis: MagicMock
    ):
        """The give-back is one script, so the read and the delete cannot be split
        by another worker taking the lease in between."""
        redis_client.client = mock_aioredis
        mock_aioredis.expire = AsyncMock(side_effect=[True, False])
        mock_aioredis.eval = AsyncMock(side_effect=[1, 0])

        assert await redis_client.expire("lease", 30) is True
        assert await redis_client.expire("lease", 30) is False
        assert await redis_client.delete_if_equal("lease", "me") is True
        assert await redis_client.delete_if_equal("lease", "me") is False

        script = mock_aioredis.eval.await_args.args
        assert "del" in script[0]
        assert script[1:] == (1, "lease", "me")

    @pytest.mark.anyio
    async def test_a_lease_cannot_be_touched_while_not_connected(self, redis_client: RedisClient):
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.expire("lease", 30)
        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.delete_if_equal("lease", "me")

    @pytest.mark.anyio
    async def test_delete(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test deleting a key."""
        redis_client.client = mock_aioredis

        result = await redis_client.delete("test_key")

        assert result == 1
        mock_aioredis.delete.assert_called_once_with("test_key")

    @pytest.mark.anyio
    async def test_delete_not_connected(self, redis_client: RedisClient):
        """Test deleting when not connected raises error."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.delete("test_key")

    @pytest.mark.anyio
    async def test_exists(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test checking if key exists."""
        redis_client.client = mock_aioredis

        result = await redis_client.exists("test_key")

        assert result is True
        mock_aioredis.exists.assert_called_once_with("test_key")

    @pytest.mark.anyio
    async def test_exists_not_connected(self, redis_client: RedisClient):
        """Test exists when not connected raises error."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await redis_client.exists("test_key")

    @pytest.mark.anyio
    async def test_ping_connected(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test ping when connected."""
        redis_client.client = mock_aioredis

        result = await redis_client.ping()

        assert result is True
        mock_aioredis.ping.assert_called_once()

    @pytest.mark.anyio
    async def test_ping_not_connected(self, redis_client: RedisClient):
        """Test ping when not connected returns False."""
        redis_client.client = None

        result = await redis_client.ping()

        assert result is False

    @pytest.mark.anyio
    async def test_ping_exception(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test ping when exception occurs returns False."""
        redis_client.client = mock_aioredis
        mock_aioredis.ping = AsyncMock(side_effect=Exception("Connection error"))

        result = await redis_client.ping()

        assert result is False

    def test_raw_property(self, redis_client: RedisClient, mock_aioredis: MagicMock):
        """Test accessing raw client."""
        redis_client.client = mock_aioredis

        result = redis_client.raw

        assert result == mock_aioredis

    def test_raw_property_not_connected(self, redis_client: RedisClient):
        """Test accessing raw client when not connected raises error."""
        redis_client.client = None

        with pytest.raises(RuntimeError, match="not connected"):
            _ = redis_client.raw

    @pytest.mark.anyio
    async def test_list_verbs_read_a_queue_oldest_first(
        self, redis_client: RedisClient, mock_aioredis: MagicMock
    ):
        """A live browse's command queue: take one, wait for one, read them all."""
        mock_aioredis.lpop = AsyncMock(return_value="first")
        mock_aioredis.blpop = AsyncMock(side_effect=[("queue", "second"), None])
        mock_aioredis.lrange = AsyncMock(return_value=["a", "b"])
        redis_client.client = mock_aioredis

        assert await redis_client.pop_left("queue") == "first"
        assert await redis_client.wait_pop_left("queue", 1.5) == "second"
        assert await redis_client.wait_pop_left("queue", 1.5) is None
        assert await redis_client.list_range("queue") == ["a", "b"]
        mock_aioredis.blpop.assert_awaited_with(["queue"], timeout=1.5)
        mock_aioredis.lrange.assert_awaited_once_with("queue", 0, -1)

    @pytest.mark.anyio
    async def test_hash_all_reads_every_field(self, redis_client: RedisClient, mock_aioredis):
        mock_aioredis.hgetall = AsyncMock(return_value={"u-1": "1700000000.0"})
        redis_client.client = mock_aioredis

        assert await redis_client.hash_all("room") == {"u-1": "1700000000.0"}

    @pytest.mark.anyio
    @pytest.mark.parametrize("verb", ["pop_left", "wait_pop_left", "list_range", "hash_all"])
    async def test_list_verbs_not_connected(self, redis_client: RedisClient, verb: str):
        redis_client.client = None
        args = ("queue", 1.0) if verb == "wait_pop_left" else ("queue",)

        with pytest.raises(RuntimeError, match="not connected"):
            await getattr(redis_client, verb)(*args)
