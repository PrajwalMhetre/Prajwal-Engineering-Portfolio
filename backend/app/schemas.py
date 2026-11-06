from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContactCreate(InputModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)

    @field_validator("name", "subject", "message", mode="before")
    @classmethod
    def clean_text(cls, value: str):
        return value.strip() if isinstance(value, str) else value


class ContactCreated(BaseModel):
    id: str
    status: str
    created_at: datetime


class ProjectFields(InputModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    title: str = Field(min_length=2, max_length=180)
    category: str = Field(pattern=r"^(semiconductor|software|embedded|wireless|ai|cloud)$")
    summary: str = Field(min_length=10, max_length=500)
    description: str = Field(default="", max_length=12000)
    tech_stack: str = Field(default="", max_length=1000)
    repository_url: HttpUrl | None = None
    demo_url: HttpUrl | None = None
    image_path: str | None = Field(
        default=None,
        pattern=r"^projects/[A-Za-z0-9_-]+/[0-9a-f]{32}\.(jpg|png|webp)$",
    )
    featured: bool = False
    published: bool = True

    @field_validator("title", "summary", "description", "tech_stack", mode="before")
    @classmethod
    def clean_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProjectCreate(ProjectFields):
    pass


class ProjectUpdate(InputModel):
    title: str = Field(default=None, min_length=2, max_length=180)
    category: str = Field(default=None, pattern=r"^(semiconductor|software|embedded|wireless|ai|cloud)$")
    summary: str = Field(default=None, min_length=10, max_length=500)
    description: str = Field(default=None, max_length=12000)
    tech_stack: str = Field(default=None, max_length=1000)
    repository_url: HttpUrl | None = None
    demo_url: HttpUrl | None = None
    image_path: str | None = Field(
        default=None,
        pattern=r"^projects/[A-Za-z0-9_-]+/[0-9a-f]{32}\.(jpg|png|webp)$",
    )
    featured: bool = None
    published: bool = None

    @field_validator("title", "summary", "description", "tech_stack", mode="before")
    @classmethod
    def clean_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProjectRead(ProjectFields):
    model_config = ConfigDict(extra="ignore")

    id: str
    created_at: datetime
    updated_at: datetime
    view_count: int = 0


class ProjectPage(BaseModel):
    items: list[ProjectRead]
    next_cursor: str | None = None


class ContactRead(BaseModel):
    id: str
    name: str
    email: EmailStr
    subject: str
    message: str
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class ContactPage(BaseModel):
    items: list[ContactRead]
    next_cursor: str | None = None


class MessageStatusUpdate(InputModel):
    status: str = Field(pattern=r"^(new|read|replied|archived|spam)$")


class AdminLogin(InputModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class AuthVerify(InputModel):
    id_token: str = Field(min_length=1, max_length=8192)
    refresh_token: str = Field(min_length=1, max_length=8192)


class AdminProjectRead(BaseModel):
    authenticated: bool
    email: EmailStr


class UploadRead(BaseModel):
    path: str
    content_type: str
