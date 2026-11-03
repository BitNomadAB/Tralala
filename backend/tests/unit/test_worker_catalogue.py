"""The worker catalogue tells the truth: each tool runs, is documented and tested, stays a worker's.

``app/services/agent_tools.py`` is the only description of what an external worker token may call
(AGENTS.md rule 13), and ``/llms.txt`` and the MCP ``tools/list`` payload are generated from it.
This guard reads the catalogue, the generated text and payload, and the syntax tree of every handler
and of the service methods it calls, and holds each entry to five rules:

1. **Handler.** The handler is a module-level function of the catalogue module taking
   ``(services, actor, args)``, so the guard can read it. The handlers are defined in
   ``agent_tools_read.py`` and ``agent_tools_write.py`` and re-exported by ``agent_tools.py``, so
   the guard reads those three files as the catalogue module's source.
2. **Documented.** ``/llms.txt`` has a ``### name (requires ...)`` section with exactly the entry's
   scopes and its description, and ``tools/list`` for an actor holding every scope carries the
   entry's name, description and input schema. Neither lists a tool the catalogue lacks, and both
   keep the catalogue's order.
3. **Never wider than its handler.** Every declared scope is checked by one of the
   ``actor.require("<scope>")`` statements that *open* a body (after the docstring, before anything
   else runs): of the handler, of a catalogue-module helper the handler passes the actor to
   (followed transitively), or of a service method the handler or such a helper calls as
   ``services.<attribute>.<method>(..., actor, ...)`` (one level: the method's own body). The other
   way round, every scope an ``actor.require`` anywhere in those bodies names is declared, so
   ``tools/list`` never offers a tool to a token that is then refused.
4. **No human decision.** No tool name contains a stem of a decision AGENTS.md rule 11a reserves for
   a person, and no handler reaches (itself or through a catalogue-module helper) a service method
   that takes one: the methods listed per decision, and every service method that opens with
   ``require_human``. ``GATED`` lists the methods a tool may reach because the method refuses a
   token for the human part itself; the guard checks that the refusal is still there.
5. **Tested.** A unit test other than this guard names the tool (its name as a string literal) or
   its handler (imported from, or read as an attribute of, the catalogue module). ``UNTESTED_TOOLS``
   lists the exceptions with their reason; an exception that is no longer needed fails.

Every rule is a function over plain data (catalogue entries and source text), so the negative
fixtures at the bottom run the same functions on small sources that each break one rule.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import SCOPES, ActorContext
from app.services import agent_tools
from app.services.agent_tools import AgentTool, tool_catalog

UNIT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = UNIT_ROOT.parents[1]
SERVICES_ROOT = BACKEND_ROOT / "app" / "services"
CATALOGUE_FILES = tuple(
    SERVICES_ROOT / name
    for name in ("agent_tools.py", "agent_tools_read.py", "agent_tools_write.py")
)
COMPOSITION_ROOT = SERVICES_ROOT / "__init__.py"
AGENTS_MD = BACKEND_ROOT.parent / "AGENTS.md"
CATALOGUE_MODULE = agent_tools.__name__

Function = ast.FunctionDef | ast.AsyncFunctionDef
CHECKS = frozenset({"require", "require_human"})
HUMAN_CODE = "human_action_required"


@dataclass(frozen=True, slots=True)
class HumanDecision:
    """One decision AGENTS.md rule 11a reserves for a person."""

    action: str  # the rule's own words
    stems: tuple[str, ...]  # a tool name containing one of these takes the decision
    methods: tuple[str, ...]  # the service methods that take it, as "Class.method"


# AGENTS.md rule 11a: "Approving analysis or a RoadMap, resetting a scope, editing Info,
# confirming a human-only Ticket, accepting implementation or QA, and finalizing a Loop reject
# agent tokens (`403 human_action_required`) regardless of scope, and are never registered as
# WebMCP tools."
HUMAN_DECISIONS: tuple[HumanDecision, ...] = (
    HumanDecision(
        "approving analysis or a RoadMap", ("approv", "review"), ("LoopDocumentService.review",)
    ),
    HumanDecision("resetting a scope", ("reset",), ("LoopDocumentService.reset",)),
    # The worker that agreed the intent writes it while the Loop is speculative (public_docs/
    # Loops.md); the edit the rule reserves is the one after planning started, which save_info
    # refuses to a token itself (see GATED). So `write_info` is a worker's tool and no method is
    # listed here.
    HumanDecision("editing Info", ("edit_info", "update_info", "replace_info", "set_info"), ()),
    HumanDecision(
        "confirming a human-only Ticket", ("confirm",), ("LoopService.confirm_human_ticket",)
    ),
    HumanDecision(
        "accepting implementation or QA",
        ("accept",),
        ("LoopQaService.accept_implementation", "LoopQaService.decide"),
    ),
    HumanDecision(
        "finalizing a Loop",
        ("finaliz", "finalis"),
        (
            "LoopHistoryService.finalize",
            "LoopQaService.accept_implementation",
            "LoopQaService.decide",
        ),
    ),
)
# Service methods a tool may reach although they can take a rule-11a decision, because the method
# refuses a token for that part itself: it, or a method of its class it calls on `self`, calls
# `require_human` or raises `human_action_required`.
GATED: Mapping[str, str] = MappingProxyType(
    {
        # A token may write Info only while the Loop is draft or analysis_review.
        "LoopDocumentService.save_info": "editing Info",
        # Completing a Ticket that requires a person is refused to a token.
        "CardService.update": "confirming a human-only Ticket",
    }
)

_ON_SERVICES = (
    "the handler runs on the Services composition root, which the unit suite cannot build; it gets "
    "unit tests on fakes when agent_tools moves onto repositories"
)
# Tools no unit test names yet, each with its reason.
UNTESTED_TOOLS: Mapping[str, str] = MappingProxyType(
    dict.fromkeys(
        (
            "assign_ticket",
            "move_ticket",
            "comment_ticket",
            "create_loop",
            "write_info",
            "run_analysis",
            "run_roadmap",
            "ask_agents",
            "read_discussion",
            "reply_discussion",
        ),
        _ON_SERVICES,
    )
)


# --- what the guard reads ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entry:
    """One catalogue entry as plain data."""

    name: str
    scopes: tuple[str, ...]
    description: str
    input_schema: Mapping[str, object]
    handler: str  # the handler's name in the catalogue module; empty when it is not one


@dataclass(frozen=True, slots=True)
class Code:
    """The syntax the guard reads: the catalogue module, the composition root and the services."""

    functions: Mapping[str, Function]  # module-level functions of the catalogue module's files
    services: Mapping[str, str]  # `Services` attribute -> the class it is built from
    methods: Mapping[str, Function]  # "Class.method" of every class the composition root builds


@dataclass(frozen=True, slots=True)
class Reach:
    """What one handler does, read from its body and from the bodies it hands the actor to."""

    opening: frozenset[str]  # scopes checked by the opening `actor.require` statements
    checked: frozenset[str]  # every scope an `actor.require` in those bodies names
    methods: frozenset[str]  # every service method reached, as "Class.method"
    problems: tuple[str, ...]


def handler_name(tool: AgentTool) -> str:
    """The handler's name when it is a module-level function of the catalogue module, else ""."""
    name: str = getattr(tool.handler, "__name__", "")
    if vars(agent_tools).get(name) is tool.handler:
        return name
    return ""


def entries(catalogue: Mapping[str, AgentTool]) -> list[Entry]:
    return [
        Entry(tool.name, tool.scopes, tool.description, tool.input_schema, handler_name(tool))
        for tool in catalogue.values()
    ]


def module_functions(source: str, filename: str = "<catalogue>") -> dict[str, Function]:
    tree = ast.parse(source, filename)
    return {node.name: node for node in tree.body if isinstance(node, Function)}


def composition(source: str) -> tuple[dict[str, str], dict[str, str]]:
    """`Services` attribute -> class, and class -> the sibling module it is imported from."""
    tree = ast.parse(source, "<composition root>")
    imported: dict[str, str] = {}
    attributes: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
        if not (isinstance(node, ast.ClassDef) and node.name == "Services"):
            continue
        for item in node.body:
            if not (isinstance(item, ast.FunctionDef) and item.name == "__init__"):
                continue
            for statement in ast.walk(item):
                if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                    target, value = statement.targets[0], statement.value
                elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                    target, value = statement.target, statement.value
                else:
                    continue
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                ):
                    attributes[target.attr] = value.func.id
    return attributes, imported


def build_code(catalogue: Sequence[str], root: str, read_module: Callable[[str], str]) -> Code:
    functions: dict[str, Function] = {}
    for source in catalogue:
        functions.update(module_functions(source))
    attributes, imported = composition(root)
    trees: dict[str, ast.Module] = {}
    methods: dict[str, Function] = {}
    for class_name in sorted(set(attributes.values())):
        module = imported.get(class_name)
        if module is None:
            continue  # built from elsewhere (storage, repositories); reach() reports a call to it
        if module not in trees:
            trees[module] = ast.parse(read_module(module), f"{module}.py")
        for node in trees[module].body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, Function):
                        methods[f"{class_name}.{item.name}"] = item
    return Code(functions, attributes, methods)


def read_service_module(module: str) -> str:
    return (SERVICES_ROOT / f"{module}.py").read_text(encoding="utf-8")


# --- reading a body ------------------------------------------------------------------------------


def _parameters(function: Function) -> list[str]:
    return [argument.arg for argument in (*function.args.posonlyargs, *function.args.args)]


def _all_parameters(function: Function) -> set[str]:
    return {*_parameters(function), *(argument.arg for argument in function.args.kwonlyargs)}


def _body(function: Function) -> list[ast.stmt]:
    """The statements after the docstring."""
    body = function.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


def _literal(call: ast.Call) -> str | None:
    first = call.args[0] if len(call.args) == 1 else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def opening_checks(function: Function) -> list[tuple[str, str, str | None]]:
    """The checks that open the body: (parameter, "require" or "require_human", literal scope)."""
    parameters = _all_parameters(function)
    checks: list[tuple[str, str, str | None]] = []
    for statement in _body(function):
        call = statement.value if isinstance(statement, ast.Expr) else None
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in parameters
            and call.func.attr in CHECKS
        ):
            break
        checks.append((call.func.value.id, call.func.attr, _literal(call)))
    return checks


def _opening_scopes(function: Function, actor: str) -> set[str]:
    return {
        scope
        for receiver, check, scope in opening_checks(function)
        if receiver == actor and check == "require" and scope is not None
    }


def _required(function: Function, actor: str, where: str) -> tuple[set[str], list[str]]:
    """Every scope an `actor.require(...)` in the body names, and the calls that compute one."""
    scopes: set[str] = set()
    problems: list[str] = []
    for call in _calls(function):
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "require"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == actor
        ):
            scope = _literal(call)
            if scope is None:
                problems.append(f"{where}:{call.lineno} checks a scope the guard cannot read")
            else:
                scopes.add(scope)
    return scopes, problems


def _calls(function: Function) -> Iterator[ast.Call]:
    return (node for node in ast.walk(function) if isinstance(node, ast.Call))


def _service_call(call: ast.Call, services: str | None) -> tuple[str, str] | None:
    """`services.<attribute>.<method>(...)` as (attribute, method)."""
    func = call.func
    if (
        services is not None
        and isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == services
    ):
        return func.value.attr, func.attr
    return None


def _receiver(call: ast.Call, function: Function, name: str | None, offset: int) -> str | None:
    """The parameter of ``function`` that ``call`` passes the local ``name`` to."""
    if name is None:
        return None
    positional = _parameters(function)[offset:]
    for index, argument in enumerate(call.args):
        if isinstance(argument, ast.Name) and argument.id == name and index < len(positional):
            return positional[index]
    accepted = _all_parameters(function)
    for keyword in call.keywords:
        if (
            keyword.arg in accepted
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == name
        ):
            return keyword.arg
    return None


def reach(code: Code, handler: str) -> Reach:
    """Follow the handler into catalogue-module helpers and one level into service methods."""
    opening: set[str] = set()
    checked: set[str] = set()
    methods: set[str] = set()
    problems: list[str] = []
    parameters = _parameters(code.functions[handler])
    pending: list[tuple[str, str | None, str | None]] = [(handler, parameters[0], parameters[1])]
    seen: set[tuple[str, str | None, str | None]] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        name, services, actor = current
        function = code.functions[name]
        if actor is not None:
            opening |= _opening_scopes(function, actor)
            found, unreadable = _required(function, actor, name)
            checked |= found
            problems += unreadable
        for call in _calls(function):
            target = _service_call(call, services)
            if target is not None:
                attribute, method_name = target
                key = f"{code.services.get(attribute)}.{method_name}"
                method = code.methods.get(key)
                if method is None:
                    problems.append(
                        f"{name}:{call.lineno} calls services.{attribute}.{method_name}, which is "
                        "not a service method the guard can read"
                    )
                    continue
                methods.add(key)
                bound = _receiver(call, method, actor, 1)
                if bound is not None:
                    opening |= _opening_scopes(method, bound)
                    found, unreadable = _required(method, bound, key)
                    checked |= found
                    problems += unreadable
            elif isinstance(call.func, ast.Name) and call.func.id in code.functions:
                helper = code.functions[call.func.id]
                pending.append(
                    (
                        call.func.id,
                        _receiver(call, helper, services, 0),
                        _receiver(call, helper, actor, 0),
                    )
                )
    return Reach(frozenset(opening), frozenset(checked), frozenset(methods), tuple(problems))


# --- the rules -----------------------------------------------------------------------------------


def _readable(entry: Entry, code: Code) -> bool:
    function = code.functions.get(entry.handler)
    return function is not None and len(_parameters(function)) == 3


def handler_problems(catalogue: Sequence[Entry], code: Code) -> list[str]:
    problems: list[str] = []
    for entry in catalogue:
        if entry.handler not in code.functions:
            problems.append(f"{entry.name} has no handler in the catalogue module")
        elif not _readable(entry, code):
            problems.append(f"{entry.name}: {entry.handler} does not take (services, actor, args)")
    return problems


def _listing_problems(where: str, listed: Sequence[str], catalogue: Sequence[Entry]) -> list[str]:
    known = [entry.name for entry in catalogue]
    problems = [f"{name} is missing from {where}" for name in known if name not in listed]
    problems += [
        f"{where} lists {name}, which the catalogue lacks"
        for name in dict.fromkeys(listed)
        if name not in known
    ]
    problems += [
        f"{where} lists {name} twice"
        for name in dict.fromkeys(listed)
        if listed.count(name) > 1
    ]
    if not problems and list(listed) != known:
        problems.append(f"{where} lists the tools in another order than the catalogue")
    return problems


HEADING = re.compile(r"^### (\S+) \(requires (.*)\)$", re.MULTILINE)


def documentation_problems(
    catalogue: Sequence[Entry], bootstrap: str, listed: Sequence[Mapping[str, object]]
) -> list[str]:
    """`/llms.txt` and `tools/list` (for an actor holding every scope) against the catalogue."""
    headings = list(HEADING.finditer(bootstrap))
    sections: dict[str, tuple[str, str]] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(bootstrap)
        body = bootstrap[heading.end() : end].split("\n## ", 1)[0]
        sections.setdefault(heading.group(1), (heading.group(2), body))
    offered = [str(item.get("name")) for item in listed]
    problems = _listing_problems("/llms.txt", [heading.group(1) for heading in headings], catalogue)
    problems += _listing_problems("tools/list", offered, catalogue)
    for entry in catalogue:
        required = ", ".join(f"`{scope}`" for scope in entry.scopes)
        if entry.name in sections:
            scopes, body = sections[entry.name]
            if scopes != required:
                problems.append(
                    f"/llms.txt says {entry.name} requires {scopes}, the catalogue {required}"
                )
            if entry.description not in body:
                problems.append(f"/llms.txt does not carry the description of {entry.name}")
        if entry.name in offered:
            item = listed[offered.index(entry.name)]
            if (
                item.get("description") != entry.description
                or item.get("inputSchema") != entry.input_schema
            ):
                problems.append(
                    f"tools/list carries another description or schema for {entry.name}"
                )
    return problems


def scope_problems(catalogue: Sequence[Entry], code: Code) -> list[str]:
    problems: list[str] = []
    for entry in catalogue:
        if not _readable(entry, code):
            continue
        found = reach(code, entry.handler)
        problems += [f"{entry.name}: {problem}" for problem in found.problems]
        problems += [
            f"{entry.name} is wider than its handler: it declares `{scope}`, which no opening "
            f"actor.require of {entry.handler} or of a function it passes the actor to checks"
            for scope in entry.scopes
            if scope not in found.opening
        ]
        problems += [
            f"{entry.name}: {entry.handler} checks `{scope}`, which the tool does not declare, so "
            "tools/list offers it to a token that is then refused"
            for scope in sorted(found.checked - set(entry.scopes))
        ]
    return problems


def refuses_a_token(code: Code, method: str) -> bool:
    """The method, or a method of its class it calls on `self`, refuses a non-person."""
    owner = method.split(".", 1)[0]
    pending = [method]
    seen: set[str] = set()
    while pending:
        key = pending.pop()
        function = code.methods.get(key)
        if key in seen or function is None:
            continue
        seen.add(key)
        for call in _calls(function):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "require_human":
                return True
            if any(
                keyword.arg == "code"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == HUMAN_CODE
                for keyword in call.keywords
            ):
                return True
            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
            ):
                pending.append(f"{owner}.{call.func.attr}")
    return False


def _opens_with_require_human(function: Function) -> bool:
    return any(check == "require_human" for _, check, _ in opening_checks(function))


def human_problems(
    catalogue: Sequence[Entry],
    code: Code,
    decisions: Sequence[HumanDecision] = HUMAN_DECISIONS,
    gated: Mapping[str, str] = GATED,
) -> list[str]:
    reserved: dict[str, str] = {}
    for decision in decisions:
        for method in decision.methods:
            reserved.setdefault(method, decision.action)
    problems = [
        f"the rule-11a list names {method}, which the services no longer define"
        for method in [*reserved, *gated]
        if method not in code.methods
    ]
    for entry in catalogue:
        problems += [
            f"{entry.name}: the name says {stem!r}, which is {decision.action} (AGENTS.md rule 11a)"
            for decision in decisions
            for stem in decision.stems
            if stem in entry.name
        ]
        if not _readable(entry, code):
            continue
        for method in sorted(reach(code, entry.handler).methods):
            if method in gated:
                if not refuses_a_token(code, method):
                    problems.append(
                        f"{entry.name} reaches {method}, which no longer refuses a token for "
                        f"{gated[method]} (AGENTS.md rule 11a)"
                    )
            elif method in reserved:
                problems.append(
                    f"{entry.name} reaches {method}: {reserved[method]} is a person's decision "
                    "(AGENTS.md rule 11a)"
                )
            elif _opens_with_require_human(code.methods[method]):
                problems.append(f"{entry.name} reaches {method}, which opens with require_human")
    return problems


RULE_11A = re.compile(r"\*\*Planning decisions are human decisions\.\*\* (.+?) reject agent tokens")


def rule_11a_decisions(agents_md: str) -> list[str]:
    """The decisions rule 11a lists, in its own words."""
    match = RULE_11A.search(" ".join(agents_md.split()))
    if match is None:
        return []
    return [part.strip() for part in re.split(r",\s*(?:and\s+)?", match.group(1))]


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else ""


# How a test refers to the catalogue module: by its dotted path or by the name it imports it as.
MODULE_REFERENCES = frozenset({CATALOGUE_MODULE, CATALOGUE_MODULE.rsplit(".", 1)[-1]})


def names_in_tests(sources: Mapping[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    """Every string literal in the sources, and every name imported from or read off the module."""
    strings: set[str] = set()
    handlers: set[str] = set()
    for filename, source in sources.items():
        for node in ast.walk(ast.parse(source, filename)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
            elif isinstance(node, ast.ImportFrom) and node.module == CATALOGUE_MODULE:
                handlers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Attribute) and _dotted(node.value) in MODULE_REFERENCES:
                handlers.add(node.attr)
    return frozenset(strings), frozenset(handlers)


def coverage_problems(
    catalogue: Sequence[Entry], sources: Mapping[str, str], untested: Mapping[str, str]
) -> list[str]:
    strings, handlers = names_in_tests(sources)
    problems: list[str] = []
    for entry in catalogue:
        named = entry.name in strings or (entry.handler != "" and entry.handler in handlers)
        if named and entry.name in untested:
            problems.append(f"a unit test names {entry.name} now; remove it from UNTESTED_TOOLS")
        elif not named and entry.name not in untested:
            problems.append(f"no unit test names {entry.name} or its handler")
    known = {entry.name for entry in catalogue}
    problems += [
        f"UNTESTED_TOOLS lists {name}, which the catalogue lacks"
        for name in untested
        if name not in known
    ]
    return problems


# --- the catalogue -------------------------------------------------------------------------------


EVERY_SCOPE = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="worker", scopes=frozenset(SCOPES)
)
CATALOGUE = entries(tool_catalog())


@pytest.fixture(scope="module")
def code() -> Code:
    return build_code(
        [path.read_text(encoding="utf-8") for path in CATALOGUE_FILES],
        COMPOSITION_ROOT.read_text(encoding="utf-8"),
        read_service_module,
    )


def unit_test_sources() -> dict[str, str]:
    this = Path(__file__).resolve()
    return {
        path.relative_to(BACKEND_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(UNIT_ROOT.rglob("test_*.py"))
        if path.resolve() != this and "__pycache__" not in path.parts
    }


def test_every_tool_has_a_handler_the_guard_can_read(code: Code) -> None:
    assert handler_problems(CATALOGUE, code) == []


def test_every_tool_is_in_llms_txt_and_tools_list(settings: Settings) -> None:
    problems = documentation_problems(CATALOGUE, render_bootstrap(settings), tool_list(EVERY_SCOPE))
    assert problems == []


def test_tools_list_offers_nothing_without_a_scope() -> None:
    nobody = ActorContext(actor_id="agent-2", actor_type="agent", actor_name="idle")
    assert tool_list(nobody) == []


def test_no_tool_is_wider_than_its_handler(code: Code) -> None:
    assert scope_problems(CATALOGUE, code) == []


def test_no_tool_takes_a_human_decision(code: Code) -> None:
    assert human_problems(CATALOGUE, code) == []


def test_the_human_decisions_are_rule_11a() -> None:
    listed = rule_11a_decisions(AGENTS_MD.read_text(encoding="utf-8"))
    assert [text.casefold() for text in listed] == [
        decision.action.casefold() for decision in HUMAN_DECISIONS
    ]


def test_every_tool_is_named_by_a_unit_test() -> None:
    assert coverage_problems(CATALOGUE, unit_test_sources(), UNTESTED_TOOLS) == []


# --- negative fixtures ---------------------------------------------------------------------------


FIXTURE_ROOT = """
from .cards import CardService
from .documents import LoopDocumentService
from .loops import LoopService


class Services:
    def __init__(self, settings):
        self.settings = settings
        self.card = CardService(settings)
        self.loop_document: LoopDocumentService = LoopDocumentService(settings)
        self.loop = LoopService(settings)
"""
FIXTURE_CARDS = """
class CardService:
    def get(self, board_id, card_id):
        return {}

    def update(self, actor, board_id, card_id, payload):
        actor.require("cards:write")
        self._complete(actor, payload)
        return {}

    def _complete(self, actor, payload):
        if payload.completed:
            actor.require_human("Confirming this Ticket")
"""
FIXTURE_DOCUMENTS = """
class LoopDocumentService:
    def review(self, actor, board_id, loop_id):
        actor.require_human("Approving an analysis")
        actor.require("loops:review")

    def save_info(self, actor, board_id, loop_id, content):
        actor.require("loops:write")
        if not actor.is_user:
            raise Forbidden("Info is a person's decision", code="human_action_required")
"""
FIXTURE_LOOPS = """
class LoopService:
    def cancel(self, actor, board_id, loop_id):
        actor.require_human("Cancelling a Loop")
        actor.require("loops:write")
"""
FIXTURE_HANDLERS = '''
def _read(services, actor, args):
    """Read a Ticket."""
    actor.require("cards:read")
    return services.card.get(args["board_id"], args["card_id"])


def _assign(services, actor, args):
    return services.card.update(actor, args["board_id"], args["card_id"], args)


def _store(services, who, args):
    who.require("loops:write")
    return services.loop_document.save_info(who, args["board_id"], args["loop_id"], args["text"])


def _write_info(services, actor, args):
    return _store(services, actor, args)


def _late(services, actor, args):
    card = services.card.get(args["board_id"], args["card_id"])
    actor.require("cards:read")
    return card


def _sometimes(services, actor, args):
    if args.get("strict"):
        actor.require("cards:read")
    return services.card.get(args["board_id"], args["card_id"])


def _overreach(services, actor, args):
    actor.require("cards:read")
    return services.card.update(actor, args["board_id"], args["card_id"], args)


def _computed(services, actor, args):
    actor.require(args["scope"])
    return services.card.get(args["board_id"], args["card_id"])


def _unwired(services, actor, args):
    actor.require("boards:read")
    return services.archive.list(args["board_id"])


def _approve(services, actor, args):
    actor.require("loops:write")
    return services.loop_document.review(actor, args["board_id"], args["loop_id"])


def _cancel(services, actor, args):
    actor.require("loops:write")
    return services.loop.cancel(actor, args["board_id"], args["loop_id"])


def _two(services, actor):
    actor.require("cards:read")
'''
FIXTURE_DECISIONS = (
    HumanDecision("approving analysis or a RoadMap", ("approv",), ("LoopDocumentService.review",)),
)


def _fixture_code(documents: str = FIXTURE_DOCUMENTS) -> Code:
    modules = {"cards": FIXTURE_CARDS, "documents": documents, "loops": FIXTURE_LOOPS}
    return build_code([FIXTURE_HANDLERS], FIXTURE_ROOT, modules.__getitem__)


def _entry(name: str, handler: str, *scopes: str) -> Entry:
    return Entry(name, scopes, f"{name} does one thing.", {"type": "object"}, handler)


def _human(*catalogue: Entry, code: Code | None = None) -> list[str]:
    return human_problems(catalogue, code or _fixture_code(), FIXTURE_DECISIONS, GATED)


def test_the_composition_root_is_read_from_its_assignments() -> None:
    code = _fixture_code()
    assert dict(code.services) == {
        "card": "CardService",
        "loop_document": "LoopDocumentService",
        "loop": "LoopService",
    }
    assert "CardService._complete" in code.methods


def test_an_entry_without_a_readable_handler_fails() -> None:
    catalogue = [
        _entry("read_card", "", "cards:read"),
        _entry("read_gone", "_gone", "cards:read"),
        _entry("read_two", "_two", "cards:read"),
    ]
    assert handler_problems(catalogue, _fixture_code()) == [
        "read_card has no handler in the catalogue module",
        "read_gone has no handler in the catalogue module",
        "read_two: _two does not take (services, actor, args)",
    ]
    assert handler_problems([_entry("read_card", "_read", "cards:read")], _fixture_code()) == []


def test_a_handler_outside_the_catalogue_module_has_no_name() -> None:
    elsewhere = AgentTool(
        name="read_card",
        description="Reads a card.",
        scopes=("cards:read",),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda _services, _actor, _args: {},
    )
    assert handler_name(elsewhere) == ""
    assert all(entry.handler for entry in CATALOGUE)


def test_a_tool_missing_from_llms_txt_or_tools_list_fails(settings: Settings) -> None:
    bootstrap = render_bootstrap(settings)
    listed = tool_list(EVERY_SCOPE)
    extra = _entry("archive_board", "_read", "boards:write")
    assert documentation_problems([*CATALOGUE, extra], bootstrap, listed) == [
        "archive_board is missing from /llms.txt",
        "archive_board is missing from tools/list",
    ]
    last = CATALOGUE[-1].name
    cut = bootstrap.split(f"### {last} (", 1)[0] + "## 6. REST equivalents\n"
    assert documentation_problems(CATALOGUE, cut, listed[:-1]) == [
        f"{last} is missing from /llms.txt",
        f"{last} is missing from tools/list",
    ]


def test_a_tool_documented_wrongly_fails(settings: Settings) -> None:
    bootstrap = render_bootstrap(settings)
    listed = tool_list(EVERY_SCOPE)
    first = CATALOGUE[0]
    required = ", ".join(f"`{scope}`" for scope in first.scopes)
    narrowed = bootstrap.replace(
        f"### {first.name} (requires {required})", f"### {first.name} (requires `cards:read`)"
    )
    changed = [{**listed[0], "description": "Something else."}, *listed[1:]]
    assert documentation_problems(CATALOGUE, narrowed, changed) == [
        f"/llms.txt says {first.name} requires `cards:read`, the catalogue {required}",
        f"tools/list carries another description or schema for {first.name}",
    ]
    added = bootstrap.replace(
        "## 6. REST equivalents",
        "### delete_board (requires `boards:admin`)\n\nDelete a board.\n\n## 6. REST equivalents",
    )
    assert documentation_problems(CATALOGUE, added, listed) == [
        "/llms.txt lists delete_board, which the catalogue lacks"
    ]
    swapped = [CATALOGUE[1], CATALOGUE[0], *CATALOGUE[2:]]
    assert documentation_problems(swapped, bootstrap, listed) == [
        "/llms.txt lists the tools in another order than the catalogue",
        "tools/list lists the tools in another order than the catalogue",
    ]


def test_scopes_are_covered_by_the_handler_its_helpers_or_its_services() -> None:
    catalogue = [
        _entry("read_card", "_read", "cards:read"),
        _entry("assign_card", "_assign", "cards:write"),
        _entry("write_info", "_write_info", "loops:write"),
    ]
    assert scope_problems(catalogue, _fixture_code()) == []


def test_a_tool_wider_than_its_handler_fails() -> None:
    catalogue = [
        _entry("read_card", "_read", "cards:read", "cards:write"),
        _entry("late_card", "_late", "cards:read"),
        _entry("maybe_card", "_sometimes", "cards:read"),
    ]
    problems = scope_problems(catalogue, _fixture_code())
    assert [problem.split(":", 1)[0] for problem in problems] == [
        "read_card is wider than its handler",
        "late_card is wider than its handler",
        "maybe_card is wider than its handler",
    ]
    assert "it declares `cards:write`" in problems[0]
    assert "it declares `cards:read`" in problems[1]


def test_a_handler_needing_an_undeclared_scope_fails() -> None:
    problems = scope_problems([_entry("touch_card", "_overreach", "cards:read")], _fixture_code())
    assert problems == [
        "touch_card: _overreach checks `cards:write`, which the tool does not declare, so "
        "tools/list offers it to a token that is then refused"
    ]


def test_a_check_or_a_call_the_guard_cannot_read_fails() -> None:
    catalogue = [
        _entry("read_any", "_computed", "cards:read"),
        _entry("read_archive", "_unwired", "boards:read"),
    ]
    problems = scope_problems(catalogue, _fixture_code())
    assert len(problems) == 3
    assert problems[0].startswith("read_any: _computed:")
    assert problems[0].endswith("checks a scope the guard cannot read")
    assert problems[1].startswith("read_any is wider than its handler")
    assert problems[2].startswith("read_archive: _unwired:")
    assert problems[2].endswith(
        "calls services.archive.list, which is not a service method the guard can read"
    )


def test_a_human_decision_by_name_fails() -> None:
    assert _human(_entry("approve_analysis", "_read", "cards:read")) == [
        "approve_analysis: the name says 'approv', which is approving analysis or a RoadMap "
        "(AGENTS.md rule 11a)"
    ]


def test_a_handler_reaching_a_human_decision_fails() -> None:
    assert _human(
        _entry("plan_loop", "_approve", "loops:write"),
        _entry("stop_loop", "_cancel", "loops:write"),
    ) == [
        "plan_loop reaches LoopDocumentService.review: approving analysis or a RoadMap is a "
        "person's decision (AGENTS.md rule 11a)",
        "stop_loop reaches LoopService.cancel, which opens with require_human",
    ]


def test_a_gated_method_is_allowed_only_while_it_refuses_a_token() -> None:
    catalogue = (
        _entry("write_info", "_write_info", "loops:write"),
        _entry("assign_card", "_assign", "cards:write"),
    )
    assert _human(*catalogue) == []
    refusal = 'raise Forbidden("Info is a person\'s decision", code="human_action_required")'
    assert refusal in FIXTURE_DOCUMENTS
    ungated = _fixture_code(documents=FIXTURE_DOCUMENTS.replace(refusal, "return None"))
    assert _human(*catalogue, code=ungated) == [
        "write_info reaches LoopDocumentService.save_info, which no longer refuses a token for "
        "editing Info (AGENTS.md rule 11a)"
    ]


def test_a_stale_rule_11a_list_fails() -> None:
    renamed = (HumanDecision("resetting a scope", ("reset",), ("LoopDocumentService.clear",)),)
    assert human_problems([], _fixture_code(), renamed, {"CardService.finish": "x"}) == [
        "the rule-11a list names LoopDocumentService.clear, which the services no longer define",
        "the rule-11a list names CardService.finish, which the services no longer define",
    ]


def test_rule_11a_is_read_from_the_rule_itself() -> None:
    text = (
        "11a. **Planning decisions are human decisions.** Approving a plan,\n"
        "    resetting a scope, and deleting a board reject agent tokens regardless of scope."
    )
    assert rule_11a_decisions(text) == ["Approving a plan", "resetting a scope", "deleting a board"]
    assert rule_11a_decisions("no such rule") == []


def test_an_untested_tool_and_a_stale_exception_fail() -> None:
    catalogue = [
        _entry("read_card", "_read", "cards:read"),
        _entry("move_card", "_move", "cards:write"),
        _entry("tidy_card", "_tidy", "cards:write"),
        _entry("drop_card", "_drop", "cards:write"),
    ]
    sources = {
        "test_a.py": 'def test_reads() -> None:\n    assert run("read_card")\n',
        "test_b.py": "from app.services.agent_tools import _move\n",
        "test_c.py": "def _tidy() -> None:\n    _tidy()\n\ndef test_d() -> None:\n"
        "    agent_tools._drop(None)\n",
    }
    untested = {"move_card": "reason", "gone_card": "reason"}
    assert coverage_problems(catalogue, sources, untested) == [
        "a unit test names move_card now; remove it from UNTESTED_TOOLS",
        "no unit test names tidy_card or its handler",
        "UNTESTED_TOOLS lists gone_card, which the catalogue lacks",
    ]
