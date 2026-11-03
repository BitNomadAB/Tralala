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

DEFAULT_TIMEOUT_SECONDS = 180
MAX_TIMEOUT_SECONDS = 900
MAX_OUTPUT_TOKENS = 2_000_000


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
    # The longest answer the provider may write; none sends no limit, so the provider's own
    # default applies. The cap is a sanity bound, not any provider's limit.
    max_output_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS)
    # A reasoning or local model needs minutes for a structured answer; a connection test keeps
    # its own short bound (agents_probe.PROBE_TIMEOUT_SECONDS).
    timeout_seconds: int = Field(default=DEFAULT_TIMEOUT_SECONDS, ge=1, le=MAX_TIMEOUT_SECONDS)
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
    max_output_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS)
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)
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
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    enabled: bool = True
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_tested_at: str | None = None
    # Set by the last connection test: the model answered a call that asked for a JSON schema as
    # the answer's format, so a generation sends the purpose's schema with its request.
    supports_json_schema: bool = False
    # Set by the last connection test: the model answered a call that offered one tool with a call
    # to it, so a generation run may let it read the board's repositories through tools.
    supports_tools: bool = False
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
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)


class AgentCompletionResult(OutModel):
    """The tiny real chat completion behind a connection test."""

    ok: bool
    status: str
    message: str
    latency_ms: int | None = None
    supports_json_schema: bool = False
    supports_tools: bool = False


class AgentTestResult(OutModel):
    ok: bool
    status: str
    message: str
    latency_ms: int | None = None
    models: list[str] = Field(default_factory=list)
    # What the model call found; testing a saved agent records it on the agent.
    supports_json_schema: bool = False
    supports_tools: bool = False
    # Present for an OpenAI-compatible endpoint with a model set: listing models does not prove the
    # model call works, which is the difference between a green test and a failed generation.
    completion: AgentCompletionResult | None = None
