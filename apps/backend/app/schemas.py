from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
class Login(BaseModel):
    email: str
    password: str

class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: str
    org_id: str

class ContractorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=250)
    rut: str | None = None

class ContractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    rut: str | None
    created_at: datetime

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_name: str
    mime_type: str
    declared_type: str
    detected_type: str | None
    status: str
    payment_status: str | None
    page_count: int | None
    extracted: dict
    evidence: list
    warnings: list
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    contractor_id: str | None
