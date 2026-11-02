from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import Id, LongText, Name, OutModel, StrictModel

SYSTEM_PROMPT = LongText


class RoleTemplateCreate(StrictModel):
    name: Name
    description: LongText = ""
    system_prompt: SYSTEM_PROMPT = Field(min_length=1)


class RoleTemplateUpdate(StrictModel):
    name: Name | None = None
    description: LongText | None = None
    system_prompt: SYSTEM_PROMPT | None = Field(default=None, min_length=1)


class RoleTemplateDuplicate(StrictModel):
    name: Name | None = None


class RoleTemplateOut(OutModel):
    id: str
    name: str
    description: str
    system_prompt: str
    built_in: bool
    builtin_key: str | None = None
    scope: Literal["board", "organisation"] = "board"
    customized: bool = False
    agent_count: int = 0
    created_at: str
    updated_at: str


ConnectionType = str


class AgentCreate(StrictModel):
    name: Name
    description: LongText = ""
    role_template_id: Id | None = None
    role_prompt_override: SYSTEM_PROMPT | None = Field(default=None, min_length=1)
    connection_type: str = Field(pattern="^(openai_compatible|a2a)$")
    base_url: str = Field(min_length=1, max_length=2000)
    model: Name | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    enabled: bool = True


class AgentUpdate(StrictModel):
    name: Name | None = None
    description: LongText | None = None
    role_template_id: Id | None = None
    role_prompt_override: SYSTEM_PROMPT | None = None
    connection_type: str | None = Field(default=None, pattern="^(openai_compatible|a2a)$")
    base_url: str | None = Field(default=None, min_length=1, max_length=2000)
    model: Name | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None


class AgentDuplicate(StrictModel):
    name: Name | None = None


class AgentOut(OutModel):
    id: str
    name: str
    description: str
    role_template_id: str | None = None
    role_template_name: str | None = None
    role_template_scope: Literal["board", "organisation"] = "board"
    role_template_updated_at: str | None = None
    has_role_override: bool = False
    connection_type: str
    base_url: str
    model: str | None = None
    has_api_key: bool = False
    api_key_hint: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int = 30
    enabled: bool = True
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_tested_at: str | None = None
    created_at: str
    updated_at: str


class AgentDirectoryEntry(OutModel):
    """The minimum an autocomplete needs: identity and role, never connection details."""

    id: str
    name: str
    role_template_id: str | None = None
    role_template_name: str | None = None
    role_template_scope: Literal["board", "organisation"] = "board"


class AgentTestRequest(StrictModel):
    """Probe an unsaved configuration; omit to test the stored agent."""

    connection_type: str | None = Field(default=None, pattern="^(openai_compatible|a2a)$")
    base_url: str | None = Field(default=None, min_length=1, max_length=2000)
    model: Name | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    # A model on your own network usually has no credential. Saying so explicitly is different from
    # omitting `api_key`, which means "use the one already stored on this agent".
    no_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class AgentCompletionResult(OutModel):
    """The tiny real chat completion behind a connection test."""

    ok: bool
    status: str
    message: str
    latency_ms: int | None = None


class AgentTestResult(OutModel):
    ok: bool
    status: str
    message: str
    latency_ms: int | None = None
    models: list[str] = Field(default_factory=list)
    # Present for an OpenAI-compatible endpoint with a model set: listing models does not prove the
    # model call works, which is the difference between a green test and a failed generation.
    completion: AgentCompletionResult | None = None
