"""Thin HTTP routes for local inbox operations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request

from .models import (
    CategoryStats, EmailDetail, EmailId, EmailPage, EmailQuery, ErrorResponse,
    HumanLabel, LabelPatch, SyncRequest, SyncStatus,
)
from .services import InboxService


def service(request: Request) -> InboxService:
    return request.app.state.inbox


def write_marker(marker: Annotated[Literal["1"], Header(alias="X-Meiruzone-Request")]):
    """Document the write header; middleware enforces it before reading a body."""


router = APIRouter(prefix="/api/v1", responses={
    status: {"model": ErrorResponse}
    for status in (400, 403, 404, 405, 409, 413, 415, 422, 500, 503)
})
Inbox = Annotated[InboxService, Depends(service)]


@router.get("/emails", response_model=EmailPage)
def list_emails(query: Annotated[EmailQuery, Query()], inbox: Inbox):
    return inbox.list_emails(query)


@router.get("/emails/{email_id}", response_model=EmailDetail)
def get_email(email_id: EmailId, inbox: Inbox):
    return inbox.get_email(email_id)


@router.patch("/emails/{email_id}/labels", response_model=HumanLabel,
              dependencies=[Depends(write_marker)])
def save_label(email_id: EmailId, patch: LabelPatch, inbox: Inbox):
    return inbox.save_label(email_id, patch)


@router.get("/category-stats", response_model=CategoryStats)
def category_stats(inbox: Inbox):
    return inbox.category_stats()


@router.get("/sync", response_model=SyncStatus)
def sync_status(inbox: Inbox):
    return inbox.sync_status()


@router.post("/sync", response_model=SyncStatus, dependencies=[Depends(write_marker)])
def sync(sync_request: SyncRequest, inbox: Inbox):
    return inbox.sync(sync_request)
