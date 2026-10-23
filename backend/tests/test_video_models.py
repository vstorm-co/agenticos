"""Which providers are offered for video, what each model can make, and its price.

The catalog is a file, and a file can be wrong. Most tests here are about an entry
that must *not* reach a picker; the rest about what a model can make, which the
tool checks a request against, and the price a budget is checked against.
"""

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core import secret_purposes
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretKind
from app.main import app
from app.services import video_models
from app.services.video_models import VideoPrice, price_per_second, resolution_lines, up_to


def _provider(provider_id: str) -> video_models.VideoProvider:
    entry = video_models.by_provider(provider_id)
    assert entry is not None
    return entry


class TestWhatTheCatalogOffers:
    def test_every_offered_provider_can_be_keyed_with_a_plain_api_key(self):
        for entry in video_models.providers():
            purpose = secret_purposes.get(entry.provider)
            assert purpose is not None and purpose.kind is SecretKind.API_KEY

    def test_every_model_states_what_it_makes_and_prices_every_resolution(self):
        for entry in video_models.providers():
            assert entry.base_url.startswith("https://")
            ids = [model.id for model in entry.models]
            assert len(ids) == len(set(ids))
            for model in entry.models:
                assert len(model.description) > 20
                assert 0 < model.min_seconds <= model.max_seconds
                assert model.aspect_ratios and model.resolutions and model.prices
                # Every dated row, not one day's: the agent may now choose any
                # resolution up to its ceiling, and an unpriced one is asked of the
                # budget at nothing - so a later row dropping one is caught here.
                for price in model.prices:
                    assert set(model.resolutions) <= set(price.usd_per_second), (
                        f"{model.id} from {price.since} leaves a resolution unpriced"
                    )

    def test_gemini_omni_decides_its_own_length(self):
        omni = _provider("google").model("gemini-omni-1.1-flash")
        assert omni is not None

        assert omni.duration_choosable is False
        assert omni.audio == "always"

    def test_an_unlisted_model_id_is_not_a_model(self):
        assert _provider("xai").model("grok-imagine-video-9") is None


class TestComparingResolutions:
    def test_every_catalog_resolution_has_a_height(self):
        """The catalog's names are the providers' own; a new spelling would make
        the highest resolution an author sets impossible to compare against."""
        for entry in video_models.providers():
            for model in entry.models:
                for resolution in model.resolutions:
                    assert resolution_lines(resolution) >= 240

    @pytest.mark.parametrize(
        ("name", "lines"), [("480p", 480), ("1080P", 1080), ("4k", 2160), (" 720p ", 720)]
    )
    def test_both_spellings_read_as_lines(self, name, lines):
        assert resolution_lines(name) == lines

    @pytest.mark.parametrize("name", ["HD", "", "p720", "1080i"])
    def test_a_name_of_neither_shape_is_refused(self, name):
        with pytest.raises(ValueError, match="names no resolution"):
            resolution_lines(name)

    def test_up_to_is_the_models_resolutions_under_a_ceiling_shortest_first(self):
        seedance = _provider("byteplus").model("dreamina-seedance-2-0-260128")
        assert seedance is not None

        assert up_to(seedance, "1080p") == ("480p", "720p", "1080p")
        assert up_to(seedance, "480p") == ("480p",)


class TestWhatIsDropped:
    @pytest.mark.parametrize(
        "change",
        [
            {"provider": "not-a-service"},
            {"provider": "bedrock"},
            {"models": ()},
            {"api": "websocket"},
        ],
        ids=["unknown provider", "not a plain key", "no models", "no client"],
    )
    def test_an_entry_that_would_fail_on_its_first_call(self, monkeypatch, change):
        broken = replace(video_models.CATALOG[0], **change)
        monkeypatch.setattr(video_models, "CATALOG", (broken,))

        assert video_models.providers() == ()


class TestPrices:
    def test_a_resolution_with_no_price_is_unpriced_rather_than_free(self):
        model = _provider("byteplus").models[0]

        assert price_per_second(model, "8k", on=date(2026, 10, 20)) is None

    def test_the_latest_started_price_wins_and_none_before_any(self):
        model = replace(
            _provider("xai").models[0],
            prices=(
                VideoPrice(since=date(2026, 6, 1), usd_per_second={"720p": Decimal("0.2")}),
                VideoPrice(since=date(2026, 1, 1), usd_per_second={"720p": Decimal("0.1")}),
            ),
        )

        assert price_per_second(model, "720p", on=date(2026, 7, 1)) == Decimal("0.2")
        assert price_per_second(model, "720p", on=date(2025, 12, 31)) is None


def test_the_default_follows_the_catalog_rather_than_a_constant():
    first = video_models.providers()[0]

    assert video_models.default_choice() == (first.provider, first.models[0].id)
    assert video_models.by_provider("anthropic") is None


@pytest.mark.parametrize("provider", ["google", "byteplus", "xai", "alibaba"])
def test_the_providers_this_shipped_with_stay_offered(provider: str):
    """What #2260 was built against; losing one to a typo or a purpose rename
    should fail here rather than in somebody's chat."""
    assert video_models.by_provider(provider) is not None


@pytest.mark.anyio
async def test_the_builder_reads_what_each_model_can_make(client: AsyncClient):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )

    response = await client.get("/api/v1/providers/video-models")

    assert response.status_code == 200
    body = response.json()
    providers = {item["provider"]: item for item in body["items"]}
    assert body["total"] == len(providers) == 4
    omni = providers["google"]["models"][0]
    assert omni["duration_choosable"] is False
    assert (omni["min_seconds"], omni["max_seconds"]) == (3, 10)
    assert providers["byteplus"]["name"] == "BytePlus ModelArk"
