"""No route blocks the event loop: a route is a plain ``def`` unless it awaits something.

FastAPI runs a plain ``def`` route or dependency in a worker thread and an ``async def`` one on the
event loop itself, so one blocking call in an ``async def`` (a SQLite query, a password hash, a
file write) stalls every other request until it returns. Every service call blocks, so the rule
is structural and this guard reads it from the syntax tree of ``app/api`` and ``app/main.py``
(which declares the system routes):

1. A route or dependency declared ``async def`` awaits something in its own body (``await``,
   ``async for`` or ``async with``); otherwise it is a plain ``def``.
2. An ``async def`` route or dependency calls no service and does not resolve the actor itself:
   ``get_context`` and everything reached through ``services`` run through ``run_in_threadpool``.

Ruff's ``ASYNC`` rules cover the generic blocking calls (``open``, ``time.sleep``, a synchronous
HTTP client) in any ``async def``. ``ASYNC_ROUTES`` lists the routes that stay on the event loop;
each one awaits its request body.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

# The decorator methods that register an HTTP route on a router or on the application.
ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
)
DEPENDENCY_MARKERS = frozenset({"Depends", "Security"})
# A direct call to one of these, or to anything reached through a `services` attribute, blocks.
BLOCKING_NAMES = frozenset({"get_context"})
BLOCKING_SEGMENT = "services"
# The routes that stay `async def`, by file: each awaits a body it reads in bounded chunks.
ASYNC_ROUTES = {
    "app/api/mcp.py": {"mcp_endpoint"},
    "app/api/v1/attachments.py": {"upload_attachment"},
    "app/api/v1/boards.py": {"import_board"},
}
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_AWAITS = (ast.Await, ast.AsyncFor, ast.AsyncWith)

Function = ast.FunctionDef | ast.AsyncFunctionDef


def api_files(root: Path = APP_ROOT) -> list[Path]:
    found = sorted((root / "api").rglob("*.py"))
    return [*(path for path in found if "__pycache__" not in path.parts), root / "main.py"]


def _own_nodes(function: Function) -> Iterator[ast.AST]:
    """The function's own body: a nested function, lambda or class runs somewhere else."""
    pending: list[ast.AST] = [*function.body]
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, _SCOPES):
            pending.extend(ast.iter_child_nodes(node))


def _is_route(function: Function) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_METHODS
        for decorator in function.decorator_list
    )


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def dependency_names(tree: ast.AST) -> set[str]:
    """Every function named in a ``Depends(...)`` or ``Security(...)`` marker."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name_of(node.func) not in DEPENDENCY_MARKERS:
            continue
        targets = [*node.args[:1], *(k.value for k in node.keywords if k.arg == "dependency")]
        names.update(_name_of(target) for target in targets if _name_of(target))
    return names


def _dotted(node: ast.expr) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return parts[::-1]


def _blocking_calls(function: Function) -> Iterator[ast.Call]:
    for node in _own_nodes(function):
        if not isinstance(node, ast.Call):
            continue
        path = _dotted(node.func)
        if BLOCKING_SEGMENT in path[:-1] or (len(path) == 1 and path[0] in BLOCKING_NAMES):
            yield node


def violations(
    source: str, filename: str = "<source>", dependencies: frozenset[str] = frozenset()
) -> list[str]:
    """Every ``async def`` route or dependency in ``source`` that blocks, as ``file:line: why``."""
    tree = ast.parse(source, filename)
    known = dependencies | dependency_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        kind = "route" if _is_route(node) else "dependency" if node.name in known else ""
        if not kind:
            continue
        if not any(isinstance(inner, _AWAITS) for inner in _own_nodes(node)):
            found.append(
                f"{filename}:{node.lineno}: async {kind} {node.name} never awaits; make it a def"
            )
        found += [
            f"{filename}:{call.lineno}: async {kind} {node.name} calls"
            f" {'.'.join(_dotted(call.func))} on the event loop; use run_in_threadpool"
            for call in _blocking_calls(node)
        ]
    return sorted(found)


def async_routes(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and _is_route(node)
    }


def _sources() -> dict[str, str]:
    return {
        path.relative_to(BACKEND_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in api_files()
    }


def test_no_route_or_dependency_blocks_the_event_loop() -> None:
    sources = _sources()
    dependencies = frozenset(
        name for source in sources.values() for name in dependency_names(ast.parse(source))
    )
    assert "get_context" in dependencies
    found: list[str] = []
    for filename, source in sources.items():
        found += violations(source, filename, dependencies)
    assert found == [], "Blocking work on the event loop:\n" + "\n".join(found)


def test_only_the_listed_routes_stay_async() -> None:
    found = {
        filename: names
        for filename, source in _sources().items()
        if (names := async_routes(source))
    }
    assert found == ASYNC_ROUTES


ROUTE = "@router.post('/x')\n"


@pytest.mark.parametrize(
    "source",
    [
        ROUTE + "async def x():\n    return 1",
        "@router.get('/x')\nasync def x(ctx):\n    return ctx.services.board.get('b')",
        "@app.api_route('/x', methods=['GET'])\nasync def x():\n    return {}",
        "@router.delete('/x')\nasync def x():\n    async def inner():\n        await y()\n"
        "    return inner",
        "def create_app():\n    app = FastAPI()\n\n    @app.get('/health')\n"
        "    async def health():\n        return {}\n    return app",
        ROUTE + "async def x(request, ctx):\n    data = await read(request)\n"
        "    return ctx.services.board.import_archive(ctx.actor, data)",
        ROUTE + "async def x(request):\n    ctx = get_context(request)\n"
        "    return await read(request)",
        ROUTE + "async def x(request):\n    await read(request)\n"
        "    return request.app.state.services.auth.login('a', 'b')",
        ROUTE + "async def x(request):\n    services = request.app.state.services\n"
        "    await read(request)\n    return services.auth.login('a', 'b')",
        "async def dep():\n    return 1\n\n" + ROUTE + "def x(v=Depends(dep)):\n    return v",
        "async def dep():\n    return 1\n\n"
        + ROUTE
        + "def x(v: Annotated[int, Depends(dependency=dep)]):\n    return v",
        "async def dep(request):\n    await read(request)\n"
        "    return request.app.state.services.auth.actor_from_token('t')\n\n"
        + ROUTE
        + "def x(v=Security(dep)):\n    return v",
    ],
)
def test_the_guard_flags_a_blocking_async_route(source: str) -> None:
    assert violations(source) != []


@pytest.mark.parametrize(
    "source",
    [
        ROUTE + "def x(ctx):\n    return ctx.services.board.get('b')",
        ROUTE + "async def x(request, ctx):\n    data = await read(request)\n"
        "    return await run_in_threadpool(ctx.services.board.import_archive, ctx.actor, data)",
        ROUTE + "async def x(request):\n    ctx = await run_in_threadpool(get_context, request)\n"
        "    return await run_in_threadpool(lambda: ctx.services.board.get('b'))",
        ROUTE + "async def x(request):\n    async for chunk in request.stream():\n"
        "        pass\n    return ok(request, ctx_actor.require('boards:read'))",
        "async def stream():\n    yield 1",
        "async def helper():\n    return 1",
        "@app.middleware('http')\nasync def observe(request, call_next):\n"
        "    return await call_next(request)",
        "@app.exception_handler(ApiError)\nasync def handler(request, exc):\n"
        "    return JSONResponse({})",
        "async def dep(request):\n    return await read(request)\n\n"
        + ROUTE
        + "def x(v=Depends(dep)):\n    return v",
        "def dep(request):\n    return request.app.state.services.auth.actor_from_token('t')\n\n"
        + ROUTE
        + "def x(v=Depends(dep)):\n    return v",
        "note = 'async def x(): return ctx.services.board.get(1)'",
    ],
)
def test_the_guard_accepts_a_non_blocking_route(source: str) -> None:
    assert violations(source) == []


def test_a_violation_names_the_file_the_line_and_the_fix() -> None:
    source = "import json\n\n@router.get('/x')\nasync def x(ctx):\n    return ctx.services.a.b()\n"
    assert violations(source, "app/api/v1/example.py") == [
        "app/api/v1/example.py:4: async route x never awaits; make it a def",
        "app/api/v1/example.py:5: async route x calls ctx.services.a.b on the event loop;"
        " use run_in_threadpool",
    ]
