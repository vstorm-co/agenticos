"""B64 — shop email generate puck builder."""

from app.core.exceptions import BadRequestError
from app.schemas.shop_email_generate import ShopEmailPuckBlockOut, ShopEmailPuckLlmResult
from app.services.shop_email_generate import build_merge_schema_from_puck, sanitize_body_html
import pytest


def test_build_merge_schema_from_puck() -> None:
    result = ShopEmailPuckLlmResult(
        subject="Welcome",
        blocks=[
            ShopEmailPuckBlockOut(type="EmailHeading", text="Hi {{customer.name}}"),
            ShopEmailPuckBlockOut(type="EmailButton", text="Shop", href="{{shop.url}}"),
        ],
    )
    schema = build_merge_schema_from_puck(result)
    assert schema["builder"]["version"] == 2
    puck = schema["builder"]["puck"]
    assert len(puck["content"]) == 2
    assert puck["content"][0]["type"] == "EmailHeading"
    assert "{{customer.name}}" in str(puck["content"][0]["props"]["text"])


def test_sanitize_body_html_rejects_script() -> None:
    with pytest.raises(BadRequestError):
        sanitize_body_html("<p>Hi</p><script>alert(1)</script>")
