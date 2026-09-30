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
