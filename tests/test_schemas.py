from pydantic import ValidationError
import pytest
from backend.app.schemas import ContactCreate, ProjectCreate

def test_contact_payload_is_trimmed_and_normalized():
    payload = ContactCreate(name="  Prajwal  ", email="WORK.MHETREPRAJWAL@GMAIL.COM",
                            subject="  Project enquiry ", message="  Let's discuss a build.  ")
    assert payload.name == "Prajwal"
    assert payload.subject == "Project enquiry"
    assert payload.message == "Let's discuss a build."
    assert str(payload.email) == "WORK.MHETREPRAJWAL@gmail.com"

def test_contact_honeypot_field_is_available():
    payload = ContactCreate(name="Prajwal", email="p@example.com", subject="Hello",
                            message="This is a sufficiently long message.", website="bot-filled")
    assert payload.website == "bot-filled"

def test_project_slug_and_category_are_validated():
    payload = ProjectCreate(slug="aurora-6g", title="AURORA 6G",
        category="wireless", summary="RIS-assisted wireless optimization project.")
    assert payload.slug == "aurora-6g"
    assert payload.category == "wireless"

def test_invalid_project_slug_is_rejected():
    with pytest.raises(ValidationError):
        ProjectCreate(slug="Aurora 6G", title="AURORA 6G", category="wireless",
                      summary="RIS-assisted wireless optimization project.")

def test_invalid_project_category_is_rejected():
    with pytest.raises(ValidationError):
        ProjectCreate(slug="test-project", title="Test project", category="invalid",
                      summary="A sufficiently descriptive project summary.")
