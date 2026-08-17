"""What the development provider writes to disk, and under what name.

The name is the whole of it. The file used to be called after the rendered
subject, and a subject carries whatever an organization, an inviter or an agent
is called - so `Acme / Ops` named a directory that does not exist, the write
failed into the `except` below it, and `send` answered `accepted=True` anyway.
`LOG_PROVIDER_WRITE_TO_DISK` had never been passed through until #829, so the
first deployment to switch it on would have been the first to find that out.
"""

import pytest

from app.services.email.providers.base import EmailMessage
from app.services.email.providers.log import LogProvider

pytestmark = pytest.mark.anyio


def _message(subject: str) -> EmailMessage:
    return EmailMessage(
        to=["someone@example.com"],
        from_email="noreply@example.com",
        subject=subject,
        html="<p>hello</p>",
        text="hello",
    )


async def test_a_subject_naming_a_directory_still_reaches_the_disk(tmp_path):
    provider = LogProvider(write_to_disk=True, output_dir=str(tmp_path))

    result = await provider.send(_message("Acme / Ops - agent usage this week"))

    written = list(tmp_path.glob("*.html"))
    assert result.accepted
    assert written, "send reported accepted=True and wrote nothing"
    assert written[0].read_text(encoding="utf-8") == "<p>hello</p>"


async def test_the_file_is_named_after_the_message_id(tmp_path):
    """The log line names the subject; the file name is what joins them to it."""
    provider = LogProvider(write_to_disk=True, output_dir=str(tmp_path))

    result = await provider.send(_message("Reset your password"))

    (written,) = list(tmp_path.glob("*.html"))
    assert result.provider_message_id in written.name


async def test_two_messages_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    provider = LogProvider(write_to_disk=True, output_dir=str(tmp_path))

    await provider.send(_message("Reset your password"))
    await provider.send(_message("Reset your password"))

    assert len(list(tmp_path.glob("*.html"))) == 2
