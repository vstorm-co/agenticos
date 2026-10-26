"""Dataset routes - the versioned test cases an agent's evals run over.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one dataset deliberately do not, and delegate to `DatasetService`, which
resolves the caller's access to that row - a role gate cannot see the grant
that lets a Viewer edit one shared dataset.

Every route that changes a dataset's cases answers with what the change
created, and the change is a new version: the version before it stays readable
under `?version=`.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import Auth, DatasetSvc, ScoringSvc, require
from app.api.responses import csv_response, jsonl_response
from app.core.permissions import Perm
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCaseFromMessage,
    DatasetCaseList,
    DatasetCaseQuestion,
    DatasetCaseRead,
    DatasetCaseUpdate,
    DatasetCreate,
    DatasetFileFormat,
    DatasetList,
    DatasetRead,
    DatasetSort,
    DatasetSourcePrivacy,
    DatasetUpdate,
    DatasetVersionList,
    DatasetVersionRead,
)
from app.schemas.scoring import (
    CaseScoreCreate,
    CaseScoreList,
    CaseScoreRead,
    CaseVerdict,
    DatasetScoringUpdate,
    JudgeAgreement,
    JudgeCreate,
    JudgeTemplate,
    Rescored,
    RescoreRequest,
    ReviewQueue,
    ReviewRequest,
    ReviewRequested,
    ReviewWithdrawn,
    ScoreOutcome,
)
from app.services.dataset_files import MAX_IMPORT_BYTES

router = APIRouter()


@router.get("/messages/{message_id}/source", response_model=DatasetSourcePrivacy)
async def dataset_source_privacy(message_id: UUID, service: DatasetSvc, ctx: Auth) -> Any:
    """Check the source's privacy before copying an answer into a dataset."""
    return await service.source_privacy(ctx, message_id)


@router.get("", response_model=DatasetList, dependencies=[Depends(require(Perm.DATASETS_VIEW))])
async def list_datasets(
    service: DatasetSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    sort: DatasetSort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    editable: bool = Query(
        False, description="Only the datasets the caller may change, by role or by a grant"
    ),
    runnable: bool = Query(
        False,
        description=(
            "Only the datasets the caller may run, by role or by a grant, that hold a case"
        ),
    ),
    judge: UUID | None = Query(None, description="Only the datasets of this judge"),
    agent: UUID | None = Query(
        None,
        description="Only the datasets that test this agent: made for it, checked by its "
        "eval suites, or run against it",
    ),
    asks_run: UUID | None = Query(
        None,
        description=(
            "Only the datasets whose newest version has a case asking this run's "
            "question, ignoring case and spacing; none for a run the caller may not read"
        ),
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The datasets the caller may see, each with its newest version and case count."""
    return await service.list_readable(
        ctx,
        shared_with_me=shared_with_me,
        editable=editable,
        runnable=runnable,
        search=q,
        judge_id=judge,
        agent_id=agent,
        asked_by_run=asks_run,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/judge-agreement",
    response_model=JudgeAgreement,
    dependencies=[Depends(require(Perm.DATASETS_VIEW))],
)
async def read_judge_agreement(service: ScoringSvc, ctx: Auth, judge: UUID = Query(...)) -> Any:
    """How often people agreed with a judge, over the scores it graded that somebody decided."""
    return await service.judge_agreement(ctx, judge)


@router.get(
    "/review-queue",
    response_model=ReviewQueue,
    dependencies=[Depends(require(Perm.DATASETS_VIEW))],
)
async def list_review_queue(
    service: ScoringSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Scores waiting for a person's verdict, oldest first, across the datasets the caller sees."""
    return await service.review_queue(ctx, skip=skip, limit=limit)


@router.post(
    "",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.DATASETS_EDIT))],
)
async def create_dataset(data: DatasetCreate, service: DatasetSvc, ctx: Auth) -> Any:
    """An empty dataset, visible to the organization unless it asks to start private.

    Its first case makes version 1.
    """
    return await service.create(ctx, data)


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(dataset_id: UUID, service: DatasetSvc, ctx: Auth) -> Any:
    return await service.read(ctx, dataset_id)


@router.patch("/{dataset_id}", response_model=DatasetRead)
async def update_dataset(
    dataset_id: UUID, data: DatasetUpdate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Rename or redescribe a dataset. Not a new version: no case changes."""
    return await service.update(ctx, dataset_id, data)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_dataset(dataset_id: UUID, service: DatasetSvc, ctx: Auth) -> None:
    await service.delete(ctx, dataset_id)


@router.get("/{dataset_id}/versions", response_model=DatasetVersionList)
async def list_dataset_versions(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Every version of the dataset, newest first, with what each one changed."""
    return await service.list_versions(ctx, dataset_id, skip=skip, limit=limit)


@router.get("/{dataset_id}/cases", response_model=DatasetCaseList)
async def list_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    version: int | None = Query(None, ge=1, description="A version number; the newest if omitted"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """A page of the cases one version holds, in their order."""
    return await service.list_cases(ctx, dataset_id, version=version, skip=skip, limit=limit)


@router.post("/{dataset_id}/cases/twins", response_model=DatasetCaseList)
async def find_dataset_case_twins(
    dataset_id: UUID,
    data: DatasetCaseQuestion,
    service: DatasetSvc,
    ctx: Auth,
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The newest version's cases asking this question, ignoring case and spacing.

    A read, posted: the question travels in the body, so it stays out of the
    access logs a query string is written to.
    """
    return await service.list_cases(ctx, dataset_id, limit=limit, same_input=data.input)


@router.post(
    "/{dataset_id}/cases", response_model=DatasetCaseRead, status_code=status.HTTP_201_CREATED
)
async def add_dataset_case(
    dataset_id: UUID, data: DatasetCaseCreate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Add a case written by hand. Creates the next version."""
    return await service.add_case(ctx, dataset_id, data)


@router.post(
    "/{dataset_id}/cases/from-message",
    response_model=DatasetCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_dataset_case_from_message(
    dataset_id: UUID, data: DatasetCaseFromMessage, service: DatasetSvc, ctx: Auth
) -> Any:
    """Add to dataset: an agent's answer, with the question and the turns before it.

    The answer is kept as the counter-example unless `answer_as` says it is the
    reference answer, and the newest thumbs-down comment on it becomes the note.
    """
    return await service.add_from_message(ctx, dataset_id, data)


@router.get("/{dataset_id}/cases/{case_id}", response_model=DatasetCaseRead)
async def get_dataset_case(
    dataset_id: UUID,
    case_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    version: int | None = Query(None, ge=1, description="A version number; the newest if omitted"),
) -> Any:
    """One case as a version holds it - what a link to the case opens."""
    return await service.read_case(ctx, dataset_id, case_id, version=version)


@router.patch("/{dataset_id}/cases/{case_id}", response_model=DatasetCaseRead)
async def update_dataset_case(
    dataset_id: UUID, case_id: UUID, data: DatasetCaseUpdate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Edit a case in the newest version. The edit is a new version; the old one is kept."""
    return await service.update_case(ctx, dataset_id, case_id, data)


@router.delete(
    "/{dataset_id}/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_dataset_case(
    dataset_id: UUID, case_id: UUID, service: DatasetSvc, ctx: Auth
) -> None:
    """Leave a case out of the next version. Earlier versions still hold it."""
    await service.remove_case(ctx, dataset_id, case_id)


@router.post(
    "/{dataset_id}/import",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    file: UploadFile = File(..., description="A .csv or .jsonl file of cases"),
    fmt: DatasetFileFormat | None = Query(
        None, alias="format", description="Override the format the file's extension implies"
    ),
) -> Any:
    """Append every case in a CSV or JSONL file as one new version - all rows or none."""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    return await service.import_cases(
        ctx, dataset_id, content=content, filename=file.filename, fmt=fmt
    )


@router.get("/{dataset_id}/export", response_model=None)
async def export_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    fmt: DatasetFileFormat = Query("csv", alias="format", description="csv or jsonl"),
    version: int | None = Query(None, ge=1, description="A version number; the newest if omitted"),
) -> Any:
    """One version's cases as a file that imports back unchanged."""
    result = await service.export(ctx, dataset_id, version=version, fmt=fmt)
    return jsonl_response(result) if fmt == "jsonl" else csv_response(result)


@router.put("/{dataset_id}/scoring", response_model=DatasetRead)
async def set_dataset_scoring(
    dataset_id: UUID, data: DatasetScoringUpdate, service: ScoringSvc, ctx: Auth
) -> Any:
    """Change how the dataset's cases are scored; a field left out keeps its value.

    Scores already kept are unchanged. A list given, such as the judge's criteria,
    replaces the stored one whole.
    """
    return await service.set_scoring(ctx, dataset_id, data)


@router.get("/{dataset_id}/judge-template", response_model=JudgeTemplate)
async def read_dataset_judge_template(dataset_id: UUID, service: ScoringSvc, ctx: Auth) -> Any:
    """The prompt a judge made for this dataset starts from, for the person creating it to edit.

    The default judge's prompt - the rules of grading - with what the dataset is about.
    """
    return await service.judge_template(ctx, dataset_id)


@router.post("/{dataset_id}/judge", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
async def create_dataset_judge(
    dataset_id: UUID, data: JudgeCreate, service: ScoringSvc, ctx: Auth
) -> Any:
    """Create a judge of the dataset's own and make it the one grading the dataset.

    The judge is an agent of the `judge` kind, so it needs `agents:edit` as well
    as `datasets:edit` on the dataset. The rubric stays on the dataset. Where AI
    assistance is on, grading is switched on in the same write: the judge, on a
    starting criterion when the rubric is empty, and the reference comparison
    when a case has a reference answer.
    """
    return await service.create_judge(ctx, dataset_id, data)


@router.post(
    "/{dataset_id}/cases/{case_id}/scores",
    response_model=CaseScoreRead,
    status_code=status.HTTP_201_CREATED,
)
async def score_dataset_case(
    dataset_id: UUID, case_id: UUID, data: CaseScoreCreate, service: ScoringSvc, ctx: Auth
) -> Any:
    """Score a recorded run's answer against this case, with every configured scorer.

    The judge, when configured, runs as the caller: it is budget-checked and
    appears in Activity. A judge that cannot run is recorded as skipped, and the
    case is then unscored rather than passed.
    """
    return await service.score_run(ctx, dataset_id, case_id, data)


@router.get("/{dataset_id}/scores", response_model=CaseScoreList)
async def list_dataset_scores(
    dataset_id: UUID,
    service: ScoringSvc,
    ctx: Auth,
    case_id: UUID | None = Query(None, description="Only this case's scores"),
    pending: bool = Query(False, description="Only scores waiting for a person's decision"),
    outcome: ScoreOutcome | None = Query(
        None, description="Only the scores that failed, were not graded, or passed"
    ),
    agent_id: UUID | None = Query(None, description="Only answers this agent gave"),
    eval_run_id: UUID | None = Query(None, description="Only the scores of this eval run"),
    judge: UUID | None = Query(None, description="Only the scores this judge graded"),
    tag: str | None = Query(None, max_length=64, description="Only cases carrying this tag"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The dataset's scores, newest first."""
    return await service.list_scores(
        ctx,
        dataset_id,
        case_id=case_id,
        pending=pending,
        outcome=outcome,
        agent_id=agent_id,
        eval_run_id=eval_run_id,
        judge_id=judge,
        tag=tag,
        skip=skip,
        limit=limit,
    )


@router.post("/{dataset_id}/scores/review", response_model=ReviewRequested)
async def request_case_score_reviews(
    dataset_id: UUID, data: ReviewRequest, service: ScoringSvc, ctx: Auth
) -> Any:
    """Put several of the dataset's scores in the review queue - all of them or none.

    A score already waiting, or already decided, is left as it is.
    """
    return await service.request_reviews(ctx, dataset_id, data)


@router.post("/{dataset_id}/scores/review/withdraw", response_model=ReviewWithdrawn)
async def withdraw_case_score_reviews(
    dataset_id: UUID, data: ReviewRequest, service: ScoringSvc, ctx: Auth
) -> Any:
    """Take several of the dataset's scores out of the review queue, undecided.

    All of them or none. A decided score keeps its decision.
    """
    return await service.withdraw_reviews(ctx, dataset_id, data)


@router.post("/{dataset_id}/scores/rescore", response_model=Rescored)
async def rescore_case_scores(
    dataset_id: UUID, data: RescoreRequest, service: ScoringSvc, ctx: Auth
) -> Any:
    """Grade again, on the same answers, the scores a scorer reached no verdict on.

    The agent is not run again. A score keeps its id, its eval run and any
    person's verdict; one every scorer reached a verdict on comes back in `kept`.
    """
    return await service.rescore(ctx, dataset_id, data)


@router.put("/{dataset_id}/scores/{score_id}/verdict", response_model=CaseScoreRead)
async def set_case_score_verdict(
    dataset_id: UUID, score_id: UUID, data: CaseVerdict, service: ScoringSvc, ctx: Auth
) -> Any:
    """Record a person's verdict, or withdraw it with `passed: null`.

    The verdict decides the outcome; the scorers' results, the judge's among
    them, are kept as they were.
    """
    return await service.set_verdict(ctx, dataset_id, score_id, data)


@router.post("/{dataset_id}/scores/{score_id}/review", response_model=CaseScoreRead)
async def request_case_score_review(
    dataset_id: UUID, score_id: UUID, service: ScoringSvc, ctx: Auth
) -> Any:
    """Put a score in the review queue."""
    return await service.request_review(ctx, dataset_id, score_id)
