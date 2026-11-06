from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

class ContactCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)

    @field_validator("name", "subject", "message")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()

class ContactCreated(BaseModel):
    id: int
    status: str
    created_at: datetime

class ProjectFields(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    title: str = Field(min_length=2, max_length=180)
    category: str = Field(pattern=r"^(semiconductor|software|embedded|wireless|ai|cloud)$")
    summary: str = Field(min_length=10, max_length=500)
    description: str = Field(default="", max_length=12000)
    tech_stack: str = Field(default="", max_length=1000)
    repository_url: HttpUrl | None = None
    demo_url: HttpUrl | None = None
    featured: bool = False
    published: bool = True

class ProjectCreate(ProjectFields):
    pass

class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    category: str | None = Field(default=None, pattern=r"^(semiconductor|software|embedded|wireless|ai|cloud)$")
    summary: str | None = Field(default=None, min_length=10, max_length=500)
    description: str | None = Field(default=None, max_length=12000)
    tech_stack: str | None = Field(default=None, max_length=1000)
    repository_url: HttpUrl | None = None
    demo_url: HttpUrl | None = None
    featured: bool | None = None
    published: bool | None = None

class ProjectRead(ProjectFields):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime

class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    subject: str
    message: str
    status: str
    created_at: datetime

class MessageStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(new|read|replied|archived|spam)$")
