"""Prompts for Shop email template Generate (authoring only)."""

from app.schemas.shop_email_generate import MERGE_TOKEN_HINTS

_TOKENS = ", ".join(f"{{{{{t}}}}}" for t in MERGE_TOKEN_HINTS)

EMAIL_GENERATE_HTML_SYSTEM = f"""You draft marketing/transactional email templates for e-commerce shops.
Return ONLY structured output with subject and body_html.

Rules:
- body_html must be a single HTML fragment suitable for email (table-based layout, inline styles).
- Use merge tokens where helpful: {_TOKENS}
- Do NOT include scripts, iframes, or external tracking pixels.
- Do NOT claim the email was sent — this is a merchant draft only.
- Vietnamese or English copy is fine; match the user prompt language.
- Keep width ~600px, mobile-friendly tables.
"""

EMAIL_GENERATE_PUCK_SYSTEM = f"""You draft email templates as a short list of editable blocks for a block builder.

Allowed block types ONLY:
- EmailHeader: brand (shop name), subtitle, badge (optional)
- EmailHeading: text
- EmailText: text (plain, may include merge tokens)
- EmailButton: text, href
- EmailFooter: text (small print)

Rules:
- Use merge tokens where helpful: {_TOKENS}
- Maximum 12 blocks; prefer 4–8 blocks.
- Do NOT invent block types beyond the list above.
- Vietnamese or English copy is fine; match the user prompt language.
- This is a draft for merchant review — not an sent email.
"""

OCCASION_HINTS: dict[str, str] = {
    "general": "General purpose shop email.",
    "welcome": "Welcome new customers after signup.",
    "order_confirm": "Order confirmation after checkout.",
    "order_status": "Order status update (shipped, delivered, etc.).",
    "promo": "Promotion / sale announcement.",
    "form_receipt": "Acknowledge a contact form submission.",
}
