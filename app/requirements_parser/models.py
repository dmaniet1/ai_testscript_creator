from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum


class RequirementType(str, Enum):
    TIMING = "timing"
    SIGNAL = "signal"
    RESPONSE = "response"
    PRESENCE = "presence"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Status(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    TESTED = "tested"
    FAILED = "failed"


class Requirement(BaseModel):
    id: str
    title: str
    description: str
    type: RequirementType
    protocol: str = "CAN"
    priority: Priority = Priority.MEDIUM
    parameters: Dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: str = ""
    status: Status = Status.DRAFT


class RequirementsFile(BaseModel):
    project: str
    version: str = "1.0"
    author: str = ""
    requirements: List[Requirement]
