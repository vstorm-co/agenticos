"""What a skill's improver is told when it writes edits.

The improver once listed "payment terms missing" and "no account manager" as the
skill's problems and wrote an edit for neither. Every problem it is handed must get an
edit, or be named as one the skill's text cannot fix.
"""

from app.services.authoring_evidence import EvidencePack
from app.services.authoring_worker import _skill_edits_prompt


def test_every_problem_is_asked_for_an_edit_or_a_stated_reason() -> None:
    prompt = _skill_edits_prompt(
        "fernhill-quote-format",
        "main",
        "How a Fernhill quote is laid out",
        "This quote is valid for 30 days.",
        [
            {"title": "No account manager", "summary": "The footer has no place for one"},
            {"title": "No VAT", "summary": "The total leaves VAT out"},
        ],
        EvidencePack(),
        None,
        None,
    )

    assert "Write at least one edit for every problem below" in prompt
    assert "say which and why in expected_effect" in prompt
    assert "- No account manager: The footer has no place for one" in prompt
