"""Where an attached file goes, and what the model is told about it.

The change these cover is easy to state and easy to get wrong: an agent with a
workspace should be handed a *reference* to a file, and an agent without one
should keep getting the paste it always got. Both halves matter. Pasting when
there is a workspace throws away the point of having one; referencing when there
is not leaves the model told about a file it has no tool to open.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai.messages import BinaryContent
from pydantic_ai_backends import StateBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.services import attachments as attachments_module
from app.services.attachments import AttachmentRouter, safe_name, workspace_path

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _file(**overrides: object):
    defaults: dict[str, object] = {
        "id": uuid4(),
        "filename": "raport.csv",
        "mime_type": "text/csv",
        "size": 2048,
        "storage_path": "u/1/raport.csv",
        "file_type": "text",
        "parsed_content": "month,total\njan,10\nfeb,12",
    }
    return SimpleNamespace(**{**defaults, **overrides})


@pytest.fixture
def storage(monkeypatch):
    """Whatever the router asks the file store for, it gets these bytes."""
    loaded = AsyncMock(return_value=PNG)
    monkeypatch.setattr(
        attachments_module, "get_file_storage", lambda: SimpleNamespace(load=loaded)
    )
    return loaded


def _workspace(max_bytes: int = 1024 * 1024) -> CappedStateBackend:
    return CappedStateBackend(StateBackend(), max_bytes=max_bytes)


class TestWithoutAWorkspace:
    """The behaviour that already existed, kept exactly."""

    async def test_a_parsed_file_is_pasted_whole(self, storage):
        prompt = await AttachmentRouter().build_prompt("what changed?", [_file()])

        assert "month,total" in prompt
        assert "```" in prompt

    async def test_an_image_is_sent_for_the_model_to_look_at(self, storage):
        prompt = await AttachmentRouter().build_prompt(
            "what is this?", [_file(file_type="image", mime_type="image/png")]
        )

        assert isinstance(prompt, list)
        assert isinstance(prompt[1], BinaryContent)

    async def test_a_file_nothing_could_parse_is_named_not_dropped(self, storage):
        # Silence reads as the model denying a file the transcript says arrived,
        # so the reference names it and why it cannot be read.
        prompt = await AttachmentRouter().build_prompt(
            "look", [_file(filename="dump.zip", file_type="binary", parsed_content=None)]
        )

        assert isinstance(prompt, str)
        assert "dump.zip" in prompt
        assert "could not be extracted" in prompt

    async def test_no_attachments_is_the_message_unchanged(self):
        assert await AttachmentRouter().build_prompt("hello", []) == "hello"


class TestWithAWorkspace:
    async def test_the_file_is_written_and_referenced_rather_than_pasted(self, storage):
        """The whole point: a large file stops costing its weight every turn."""
        backend = _workspace()
        chat_file = _file(parsed_content="month,total\n" + "row\n" * 500)

        prompt = await AttachmentRouter(backend).build_prompt("summarise", [chat_file])

        assert workspace_path(chat_file) in prompt
        assert backend.exists(workspace_path(chat_file))
        assert prompt.count("row") < 100

    async def test_the_reference_carries_a_head_the_model_can_judge_from(self, storage):
        backend = _workspace()

        prompt = await AttachmentRouter(backend).build_prompt("summarise", [_file()])

        assert "month,total" in prompt
        assert "First 20 lines" in prompt

    async def test_an_image_is_both_seen_and_written(self, storage):
        """A path is not a substitute for looking, and looking is not a
        substitute for being able to resize it."""
        backend = _workspace()
        chat_file = _file(file_type="image", mime_type="image/png", parsed_content=None)

        prompt = await AttachmentRouter(backend).build_prompt("crop this", [chat_file])

        assert isinstance(prompt, list)
        assert isinstance(prompt[1], BinaryContent)
        assert backend.exists(workspace_path(chat_file))

    async def test_a_large_image_is_written_and_not_also_inlined(self, storage, monkeypatch):
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOX_INLINE_IMAGE_MAX_BYTES", 100)
        backend = _workspace()
        chat_file = _file(file_type="image", mime_type="image/png", parsed_content=None, size=5000)

        prompt = await AttachmentRouter(backend).build_prompt("shrink it", [chat_file])

        assert isinstance(prompt, str)
        assert workspace_path(chat_file) in prompt

    async def test_a_pdf_keeps_its_bytes_and_gains_its_text(self, storage):
        """A shell has no tool for a PDF; the extracted text is the usable half."""
        backend = _workspace()
        chat_file = _file(
            filename="contract.pdf",
            file_type="pdf",
            mime_type="application/pdf",
            parsed_content="Clause 1. The parties agree.",
        )

        await AttachmentRouter(backend).build_prompt("summarise", [chat_file])

        assert backend.exists(workspace_path(chat_file))
        assert backend.exists(f"{workspace_path(chat_file)}.txt")

    async def test_the_same_file_on_a_later_turn_is_not_written_again(self, storage):
        """Otherwise an upload costs one write per turn for the whole chat."""
        backend = _workspace()
        chat_file = _file()
        router = AttachmentRouter(backend)

        await router.build_prompt("first", [chat_file])
        await router.build_prompt("second", [chat_file])

        assert storage.await_count == 1

    async def test_two_files_of_the_same_name_do_not_overwrite_each_other(self, storage):
        backend = _workspace()
        first, second = _file(), _file()

        await AttachmentRouter(backend).build_prompt("compare", [first, second])

        assert workspace_path(first) != workspace_path(second)
        assert backend.exists(workspace_path(first))
        assert backend.exists(workspace_path(second))

    async def test_a_full_workspace_still_names_and_samples_the_file(self, storage):
        """The file is still worth mentioning; it just cannot be stored."""
        backend = _workspace(max_bytes=1)
        chat_file = _file()

        prompt = await AttachmentRouter(backend).build_prompt("summarise", [chat_file])

        assert "month,total" in prompt
        assert chat_file.filename in prompt
        assert not backend.exists(workspace_path(chat_file))

    async def test_a_file_too_large_to_store_is_not_pasted_whole(self, storage):
        """The degradation used to run backwards.

        A file the workspace would not take is not a file to put in a prompt:
        with a 50 MB upload limit against a 4 MB document, falling back to the
        paste put up to fifty megabytes of text into one message. A file small
        enough to paste safely would have fitted in the workspace in the first
        place.
        """
        body = "\n".join(f"row-{n},{n}" for n in range(500))
        chat_file = _file(parsed_content=body)

        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("go", [chat_file])

        assert isinstance(prompt, str)
        assert "row-0" in prompt
        # The head, not the file: twenty lines of it and no more.
        assert "row-499" not in prompt
        assert "could not be written" in prompt

    async def test_an_unparsed_file_too_large_to_store_is_still_named(self, storage):
        """A zip has no text to sample, so all there is to say is that it arrived
        and could not be kept - which still beats the model never hearing of it."""
        chat_file = _file(filename="dump.zip", file_type="other", parsed_content=None)

        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("go", [chat_file])

        assert isinstance(prompt, str)
        assert "dump.zip" in prompt
        assert "could not be written" in prompt

    async def test_a_file_that_was_not_stored_is_given_no_path_to_open(self, storage):
        """Naming a path the write did not create costs the agent a tool call to
        find out the file is not there."""
        chat_file = _file()

        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("go", [chat_file])

        assert isinstance(prompt, str)
        assert workspace_path(chat_file) not in prompt

    async def test_an_oversized_image_is_not_inlined_without_a_workspace_either(
        self, storage, monkeypatch
    ):
        """The ceiling used to apply only to the workspace path.

        So the same screenshot was refused by an agent *with* a workspace and loaded
        whole by one without - the wrong way round, since the first has a path to
        offer instead and the second has nothing to fall back to.
        """
        from app.core import config as config_module

        monkeypatch.setattr(config_module.settings, "SANDBOX_INLINE_IMAGE_MAX_BYTES", 10)
        chat_file = _file(file_type="image", mime_type="image/png", filename="big.png", size=5000)

        prompt = await AttachmentRouter().build_prompt("what is this", [chat_file])

        assert isinstance(prompt, str)
        assert "big.png" in prompt
        assert "too large to show" in prompt

    async def test_an_image_inside_the_ceiling_is_still_inlined_without_a_workspace(self, storage):
        """The case that has to keep working: no workspace, and a picture the model
        can simply be shown."""
        chat_file = _file(file_type="image", mime_type="image/png", filename="small.png", size=64)

        prompt = await AttachmentRouter().build_prompt("what is this", [chat_file])

        assert isinstance(prompt, list)
        assert any(isinstance(part, BinaryContent) for part in prompt)

    async def test_an_image_too_large_to_store_is_still_shown_to_the_model(self, storage):
        """The exception, for the reason images go both ways at all: a path is no
        substitute for looking at the picture, and the inline ceiling is its own."""
        chat_file = _file(file_type="image", mime_type="image/png", filename="chart.png")

        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("look", [chat_file])

        assert isinstance(prompt, list)
        assert any(isinstance(part, BinaryContent) for part in prompt)

    async def test_a_file_the_store_cannot_load_is_named_rather_than_fatal(self, monkeypatch):
        """A routing failure must not fail the turn - the person asked a question
        and answering without the file beats not answering. But the model is told
        the file arrived and could not be processed, not left denying it."""
        monkeypatch.setattr(
            attachments_module,
            "get_file_storage",
            lambda: SimpleNamespace(load=AsyncMock(side_effect=OSError("gone"))),
        )

        prompt = await AttachmentRouter(_workspace()).build_prompt(
            "summarise", [_file(filename="raport.csv")]
        )

        assert isinstance(prompt, str)
        assert prompt.startswith("summarise")
        assert "raport.csv" in prompt
        assert "could not be processed" in prompt


class TestWhereAnAttachmentLands:
    """Inside the working directory, which is the whole of #1039.

    A sandbox resolves an absolute path as absolute. `/uploads/x` therefore
    landed at the *container's* filesystem root rather than in the bind-mounted
    work directory, and three things followed, all of them silent: the agent's
    own `ls` did not see the file, the workspace browser reads the host
    directory and so could not list it, and it died with the container. Probed
    against a live service, `write uploads/a.txt` answers
    `/workspace/uploads/a.txt` and `write /uploads/a.txt` answers
    `/uploads/a.txt`, which exists nowhere on the host.
    """

    def test_the_path_is_relative_so_the_sandbox_resolves_it_in_the_work_dir(self):
        path = workspace_path(_file(filename="report.pdf"))

        assert not path.startswith("/")
        assert path.startswith("uploads/")

    def test_a_generated_image_lands_there_too(self):
        # The same defect in the other direction: an image the agent made was
        # written outside the workspace, so it was also absent from the snapshot
        # a channel diffs to decide what to post back.
        from app.agents.capabilities.image_generation._toolset import WORKSPACE_OUTPUT_DIR

        assert not WORKSPACE_OUTPUT_DIR.startswith("/")

    async def test_the_model_is_told_the_path_the_file_is_actually_at(self, storage):
        # The reference is the only thing that tells a model where to look, so a
        # path in it that a shell cannot reach is worse than no path at all.
        backend = _workspace()
        chat_file = _file(filename="report.pdf", file_type="pdf", parsed_content="a b c")

        prompt = await AttachmentRouter(backend).build_prompt("read it", [chat_file])

        assert workspace_path(chat_file) in prompt
        assert "/uploads/" not in prompt


class TestWhatTheModelIsToldAboutAPath:
    """Where the file is, said so a model does not have to guess.

    The reference read `report.pdf (uploads/8b1e-report.pdf, 280 KB, pdf)` - the
    path one of three facts in a bracket - and the failure that started #1039 was
    a model answering "the directory is empty" after a single `ls`, about a file it
    had summarised a turn earlier.
    """

    async def test_the_path_gets_its_own_clause(self, storage):
        chat_file = _file(filename="report.csv", file_type="spreadsheet", parsed_content="a,b\n1,2")

        prompt = await AttachmentRouter(_workspace()).build_prompt("read it", [chat_file])

        assert f"in your workspace at {workspace_path(chat_file)}" in prompt

    async def test_the_extracted_text_beside_a_pdf_is_named(self, storage):
        # Written since the workspace existed and never mentioned: a shell has no
        # PDF library, so that sibling is the only half it can read.
        chat_file = _file(filename="report.pdf", file_type="pdf", parsed_content="page one")
        backend = _workspace()

        prompt = await AttachmentRouter(backend).build_prompt("read it", [chat_file])

        assert backend.exists(f"{workspace_path(chat_file)}.txt")
        assert f"beside it at {workspace_path(chat_file)}.txt" in prompt

    async def test_a_file_re_attached_still_has_its_text_named(self, storage):
        """The write is skipped on a later turn, and the sibling is still there.

        Keyed on whether *this* turn wrote it, the reference stopped naming a file
        that had not gone anywhere.
        """
        chat_file = _file(filename="report.pdf", file_type="pdf", parsed_content="page one")
        backend = _workspace()
        await AttachmentRouter(backend).build_prompt("read it", [chat_file])

        prompt = await AttachmentRouter(backend).build_prompt("again", [chat_file])

        assert f"beside it at {workspace_path(chat_file)}.txt" in prompt

    async def test_a_plain_text_file_is_named_without_inventing_a_sibling(self, storage):
        chat_file = _file(filename="notes.txt", file_type="text", parsed_content="hello")

        prompt = await AttachmentRouter(_workspace()).build_prompt("read it", [chat_file])

        assert f"in your workspace at {workspace_path(chat_file)}" in prompt
        assert "beside it at" not in prompt

    async def test_an_image_is_told_where_it_is_as_well_as_shown(self, storage):
        # Both, and the path is the half that lets it be resized, converted or read
        # by something the model writes.
        chat_file = _file(filename="chart.png", file_type="image")

        prompt = await AttachmentRouter(_workspace()).build_prompt("look", [chat_file])

        assert isinstance(prompt, list)
        assert f"in your workspace at {workspace_path(chat_file)}" in prompt[0]
        assert any(isinstance(part, BinaryContent) for part in prompt)


class TestFilenamesAreNotTrusted:
    @pytest.mark.parametrize(
        "hostile",
        ["../../etc/passwd", "..\\..\\secrets.env", "-rf", "  ", "." * 5],
    )
    def test_a_name_cannot_escape_the_uploads_directory(self, hostile: str):
        assert workspace_path(_file(filename=hostile)).startswith("uploads/")
        assert ".." not in safe_name(hostile)

    def test_a_very_long_name_is_bounded(self):
        assert len(safe_name("a" * 500)) <= 96

    def test_a_name_of_nothing_usable_still_produces_one(self):
        assert safe_name("   ") == "attachment"
        assert safe_name("///")


class TestTheReferenceReadsWell:
    async def test_megabytes_are_shown_as_megabytes(self, storage):
        prompt = await AttachmentRouter(_workspace()).build_prompt(
            "x", [_file(size=3 * 1024 * 1024)]
        )

        assert "3.0 MB" in prompt

    async def test_a_small_file_is_shown_in_kilobytes(self, storage):
        prompt = await AttachmentRouter(_workspace()).build_prompt("x", [_file(size=10)])

        assert "1 KB" in prompt

    async def test_a_file_with_no_text_is_referenced_without_a_head(self, storage):
        prompt = await AttachmentRouter(_workspace()).build_prompt(
            "x", [_file(file_type="binary", parsed_content=None)]
        )

        assert "First 20 lines" not in prompt
        assert "raport.csv" in prompt

    async def test_one_enormous_line_is_still_bounded(self, storage):
        prompt = await AttachmentRouter(_workspace()).build_prompt(
            "x", [_file(parsed_content="a" * 50_000)]
        )

        assert len(prompt) < 5_000


class TestASecondTurn:
    async def test_an_image_already_in_the_workspace_is_still_shown(self, storage):
        """The write is skipped on the second turn; the model still has to see
        the picture, so the bytes are fetched for the inline half alone."""
        backend = _workspace()
        chat_file = _file(file_type="image", mime_type="image/png", parsed_content=None)
        router = AttachmentRouter(backend)

        await router.build_prompt("what is this?", [chat_file])
        prompt = await router.build_prompt("and now?", [chat_file])

        assert isinstance(prompt, list)
        assert isinstance(prompt[1], BinaryContent)
        assert storage.await_count == 2


class TestLoadingTheRows:
    async def test_the_ids_a_client_sent_are_resolved_as_the_caller(self, monkeypatch):
        """The sender's id rides along, because the read is scoped to it (#706)."""
        from app.services import attachments as module

        caller = uuid4()
        service = SimpleNamespace(list_attached_files=AsyncMock(return_value=["row"]))
        monkeypatch.setattr(
            "app.api.deps.get_conversation_service", lambda db: service, raising=True
        )

        assert await module.load_attached_files(object(), [uuid4()], user_id=caller) == ["row"]
        assert service.list_attached_files.await_args.kwargs["user_id"] == caller


class TestWhatTheModelIsToldAboutAFailedWrite:
    """It says what happened. It used to say why, and be wrong.

    The sentence read "too large for the workspace", reasoned from the `state`
    backend's four-megabyte document - and a container write fails for reasons
    that have nothing to do with size. A 782 KB PDF attached while `sandboxd` was
    down was reported to the model as too large; the model told the person who
    attached it exactly that, and offered to work around a limit that was never
    the problem.
    """

    async def test_it_does_not_blame_the_size(self, storage):
        chat_file = _file()

        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("go", [chat_file])

        assert isinstance(prompt, str)
        assert "too large" not in prompt
        assert "could not be written" in prompt

    async def test_it_tells_the_model_not_to_invent_one(self, storage):
        """The model fills a gap where a cause is missing - it offered "because of
        its size" unprompted once the sentence stopped saying so."""
        prompt = await AttachmentRouter(_workspace(max_bytes=1)).build_prompt("go", [_file()])

        assert isinstance(prompt, str)
        assert "Do not guess at why" in prompt
