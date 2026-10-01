from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Quality, Role, Status
from app.normalise import normalise_task_name

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    organisation: str | None
    role: Role
    is_active: bool


class UserCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    name: str = Field(min_length=1, max_length=200)
    organisation: str | None = Field(default=None, max_length=200)
    role: Role
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class RequestCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=200)
    episodes_requested: int = Field(gt=0, le=100_000)
    deadline: date
    notes: str = Field(default="", max_length=5000)

    @field_validator("task_name")
    @classmethod
    def normalise_task(cls, value: str) -> str:
        value = normalise_task_name(value)
        if not value:
            raise ValueError("task_name must not be blank")
        return value

    @field_validator("deadline")
    @classmethod
    def not_in_past(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("deadline cannot be in the past")
        return value


class TransitionIn(BaseModel):
    to_status: Status
    note: str | None = Field(default=None, max_length=2000)


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: Quality
    assigned_request_id: int | None = None


class StatusEventOut(BaseModel):
    from_status: Status | None
    to_status: Status
    actor_id: int
    actor_name: str
    note: str | None
    created_at: datetime


class RequestOut(BaseModel):
    id: int
    client_id: int
    client_name: str
    task_name: str
    episodes_requested: int
    deadline: date
    notes: str
    status: Status
    created_at: datetime
    updated_at: datetime
    assigned_count: int


class RequestDetail(RequestOut):
    history: list[StatusEventOut]
    assignments: list[EpisodeOut]
    allowed_transitions: list[Status]  # what *this* user may do next; the server still re-checks


class AssignIn(BaseModel):
    episode_ids: list[str] = Field(min_length=1, max_length=500)


class EpisodePage(BaseModel):
    total: int
    items: list[EpisodeOut]


class DayRobotCount(BaseModel):
    day: date
    robot_id: str
    episodes: int


class TaskCount(BaseModel):
    task_name: str
    good_episodes: int


class AnalyticsOut(BaseModel):
    date_from: date
    date_to: date
    episodes_per_day: list[DayRobotCount]
    requests_by_status: dict[str, int]
    median_seconds_submitted_to_delivered: float | None
    top_tasks_by_good_episodes: list[TaskCount]
