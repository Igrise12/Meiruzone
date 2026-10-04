"""Validated domain records and public API shapes."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


CATEGORIES = (
    "Recruitment", "LinkedIn", "Personal", "Transaction",
    "Newsletter", "Promotion", "Spam", "Other",
)
Category = Literal[
    "Recruitment", "LinkedIn", "Personal", "Transaction",
    "Newsletter", "Promotion", "Spam", "Other",
]
CategoryFilter = Category | Literal["Unclassified"]
Priority = Literal["High", "Medium", "Low"]
EmailId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid",
    )


class Prediction(WireModel):
    category: Category | None = None
    priority: Priority | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    reason_category: str | None = None
    reason_priority: str | None = None
    model_version: str | None = None
    predicted_at: AwareDatetime | None = None


class HumanLabel(WireModel):
    category: Category | None = None
    priority: Priority | None = None
    confirmed_at: AwareDatetime
    source: Literal["manual", "correction"] = "manual"


class EmailSummary(WireModel):
    id: EmailId
    sender: str
    address: str
    subject: str
    received_at: AwareDatetime
    read: bool
    has_attachments: bool
    prediction: Prediction | None = None
    human_label: HumanLabel | None = None
    needs_review: bool = False


class EmailDetail(EmailSummary):
    body: str


class EmailQuery(WireModel):
    q: str = Field(default="", max_length=200)
    category: CategoryFilter | None = None
    priority: Priority | None = None
    needs_review: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class EmailPage(WireModel):
    items: list[EmailSummary]
    total: int
    limit: int
    offset: int


class LabelPatch(WireModel):
    category: Category | None = None
    priority: Priority | None = None
    source: Literal["manual", "correction"] = "manual"

    @model_validator(mode="after")
    def require_label(self) -> "LabelPatch":
        if self.category is None and self.priority is None:
            raise ValueError("Provide at least one label.")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("category", "priority")
        ):
            raise ValueError("Null cannot clear a label.")
        return self


class CategoryStat(WireModel):
    category: CategoryFilter
    count: int
    percentage: int


class CategoryStats(WireModel):
    total: int
    categories: list[CategoryStat]


class SyncRequest(WireModel):
    mode: Literal["recent", "unread"] = "recent"
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class SyncStatus(WireModel):
    available: bool
    demo: bool
    state: Literal["idle", "succeeded", "unavailable"]
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    imported: int = 0
    error_code: str | None = None


class FieldError(WireModel):
    field: str
    code: str
    message: str


class ErrorDetail(WireModel):
    code: str
    message: str
    fields: list[FieldError] = Field(default_factory=list)


class ErrorResponse(WireModel):
    error: ErrorDetail
