"""Every SQL statement in ``app/``, compiled by SQLite against the freshly migrated schema.

**Finding.** A statement is any text expression in ``app/`` (a string, an f-string or a ``+`` of
them) that starts with a statement keyword followed by more text. Reading the text rather than the
call that receives it also finds what reaches ``text()`` through ``rows()``, ``Registry.read()`` or
a local variable. Docstrings and the generated rows are not statements.

**Expanding.** The variable parts of an f-string follow the GCS-T11 rule (``app/core/sql.py``):
they come from a module-level tuple of literals. Each part is expanded to every text it can take,
using the real helpers of ``app.core.sql`` so the expansion cannot drift from what runs: a literal,
a module constant (also imported ones), a local assignment (``+=`` adds an optional suffix, a loop
or comprehension takes each element), an ``x if c else y``, ``sql.identifier`` (every allowed
name unless the name itself is literal), ``sql.where`` (exactly the literal selections, otherwise
no filter and each filter alone), ``sql.assignments``, ``sql.insert_columns`` and
``sql.column_list`` (all allowed columns, with a literal table alias and result prefix). Anything
else stops the build unless the site is in ``EXCEPTIONS`` with its reason.

**Checking.** Each combination of parts is compiled with ``EXPLAIN`` on Python's own ``sqlite3``,
parameters bound to NULL, so nothing is executed and no data is needed; SQLAlchemy's expanding
``IN :name`` is read as ``IN (:name)``. It proves tables, columns and syntax, not results or types.
A statement passes against whichever of the two databases accepts it (the schema rules keep a table
name to one shape across chains). With variable parts, every alternative of every part must
compile in at least one combination, because some parts only fit together (a filter on a joined
table needs the join).
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import math
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core import sql

_STATEMENT = re.compile(r"\s*(?:SELECT|INSERT|UPDATE|DELETE|WITH|REPLACE|PRAGMA|CREATE)\s+\S")
_EXPANDING_IN = re.compile(r"\bIN\s+:(\w+)")
_SQL_MODULE = "app.core.sql"
_GENERATED_PACKAGE = "app.db.generated"
MAX_COMBINATIONS = 4096

# Statements whose variable parts this check cannot follow: (file, function) -> why that is safe.
EXCEPTIONS: Mapping[tuple[str, str], str] = {}

type Function = ast.FunctionDef | ast.AsyncFunctionDef


class UnresolvedError(Exception):
    """A part of a statement whose text the check cannot know."""


# --- statements ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Slot:
    label: str
    alternatives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Statement:
    path: str
    line: int
    function: str
    parts: tuple[str | int, ...]
    slots: tuple[Slot, ...]

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"

    def size(self) -> int:
        return math.prod(len(slot.alternatives) for slot in self.slots)

    def choices(self) -> Iterator[tuple[int, ...]]:
        return itertools.product(*(range(len(slot.alternatives)) for slot in self.slots))

    def render(self, choice: Sequence[int]) -> str:
        return "".join(
            part if isinstance(part, str) else self.slots[part].alternatives[choice[part]]
            for part in self.parts
        )

    def digest(self) -> str:
        """Identifies the statement's texts, not its place: moving code does not recompile it."""
        shape = (self.parts, tuple((slot.label, slot.alternatives) for slot in self.slots))
        return hashlib.sha256(repr(shape).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Failure:
    location: str
    text: str
    error: str


# --- modules ------------------------------------------------------------------------------------


@dataclass(slots=True)
class Module:
    name: str
    path: str
    tree: ast.Module
    package: bool
    constants: dict[str, ast.expr]
    imports: dict[str, tuple[str, str | None]]


def _module_name(relative: Path) -> tuple[str, bool]:
    parts = list(relative.with_suffix("").parts)
    package = parts[-1] == "__init__"
    if package:
        parts.pop()
    return ".".join(parts), package


def load_modules(backend_root: Path) -> dict[str, Module]:
    """Every module under ``app/``, with its module-level constants and imports."""
    modules: dict[str, Module] = {}
    for path in sorted((backend_root / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(backend_root)
        name, package = _module_name(relative)
        tree = ast.parse(path.read_text(encoding="utf-8"), str(relative))
        constants: dict[str, ast.expr] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
            ):
                constants[node.target.id] = node.value
        modules[name] = Module(name, relative.as_posix(), tree, package, constants, {})
    for module in modules.values():
        module.imports = _imports(module, modules)
    return modules


def _imports(module: Module, modules: Mapping[str, Module]) -> dict[str, tuple[str, str | None]]:
    found: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = (alias.name, None)
                else:
                    top = alias.name.split(".")[0]
                    found[top] = (top, None)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = module.name if module.package else module.name.rpartition(".")[0]
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                source = f"{base}.{node.module}" if node.module else base
            else:
                source = node.module or ""
            for alias in node.names:
                submodule = f"{source}.{alias.name}"
                found[alias.asname or alias.name] = (
                    (submodule, None) if submodule in modules else (source, alias.name)
                )
    return found


# --- expansion ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scope:
    module: Module
    function: Function | None


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _parameters(function: Function) -> set[str]:
    arguments = function.args
    names = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    names += [argument for argument in (arguments.vararg, arguments.kwarg) if argument]
    return {argument.arg for argument in names}


def _own_nodes(function: Function) -> Iterator[ast.AST]:
    """The nodes of a function body, without nested functions, lambdas and classes."""
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


@dataclass(frozen=True, slots=True)
class _Binding:
    order: tuple[int, int]
    kind: str  # "value", "item", "each" or "append"
    node: ast.expr
    index: int = 0


def _bindings(function: Function, name: str) -> list[_Binding]:
    found: list[_Binding] = []

    def at(node: ast.expr) -> tuple[int, int]:
        return node.lineno, node.col_offset

    for node in _own_nodes(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(_Binding(at(node.value), "value", node.value))
                elif isinstance(target, ast.Tuple):
                    found.extend(
                        _Binding(at(node.value), "item", node.value, index)
                        for index, element in enumerate(target.elts)
                        if isinstance(element, ast.Name) and element.id == name
                    )
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                found.append(_Binding(at(node.value), "value", node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                if not isinstance(node.op, ast.Add):
                    raise UnresolvedError(f"{name} is changed by an operator other than +=")
                found.append(_Binding(at(node.value), "append", node.value))
        elif isinstance(node, ast.For | ast.comprehension):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found.append(_Binding(at(node.iter), "each", node.iter))
        elif isinstance(node, ast.withitem):
            variable = node.optional_vars
            if isinstance(variable, ast.Name) and variable.id == name:
                raise UnresolvedError(f"{name} is bound by a with statement")
    return sorted(found, key=lambda binding: binding.order)


class Resolver:
    """Turns an expression into every text it can take, or raises UnresolvedError."""

    def __init__(self, modules: Mapping[str, Module]) -> None:
        self.modules = modules

    # texts

    def texts(
        self, expr: ast.expr, scope: Scope, active: frozenset[tuple[int, str]] = frozenset()
    ) -> tuple[str, ...]:
        match expr:
            case ast.Constant(value=str() as value):
                return (value,)
            case ast.Constant(value=int() as value) if not isinstance(value, bool):
                return (str(value),)
            case ast.JoinedStr(values=values):
                pieces = [self._piece(value, scope, active) for value in values]
                return _unique(["".join(choice) for choice in itertools.product(*pieces)])
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                pairs = itertools.product(
                    self.texts(left, scope, active), self.texts(right, scope, active)
                )
                return _unique([a + b for a, b in pairs])
            case ast.IfExp(body=body, orelse=orelse):
                both = self.texts(body, scope, active) + self.texts(orelse, scope, active)
                return _unique(both)
            case ast.Name(id=name):
                return self._name(name, scope, active)
            case ast.Attribute(value=ast.Name(id=owner), attr=attribute):
                module = self._module_alias(owner, scope)
                if module is None:
                    raise UnresolvedError(f"{ast.unparse(expr)} is not a module constant")
                return self._name(attribute, Scope(module, None), active)
            case ast.Call():
                return self._call(expr, scope, active)
            case _:
                raise UnresolvedError(f"{ast.unparse(expr)} is not text this check can follow")

    def _piece(
        self, value: ast.expr, scope: Scope, active: frozenset[tuple[int, str]]
    ) -> tuple[str, ...]:
        if isinstance(value, ast.FormattedValue):
            if value.conversion != -1 or value.format_spec is not None:
                raise UnresolvedError(f"{ast.unparse(value.value)} is formatted, not inserted")
            return self.texts(value.value, scope, active)
        return self.texts(value, scope, active)

    def _name(
        self, name: str, scope: Scope, active: frozenset[tuple[int, str]]
    ) -> tuple[str, ...]:
        owner = scope.function if scope.function is not None else scope.module.tree
        key = (id(owner), name)
        if key in active:
            raise UnresolvedError(f"{name} is defined through itself")
        active = active | {key}
        if scope.function is not None:
            bindings = _bindings(scope.function, name)
            if bindings:
                return self._bound(name, bindings, scope, active)
            if name in _parameters(scope.function):
                raise UnresolvedError(f"{name} is a parameter of {scope.function.name}()")
        module = scope.module
        if name in module.constants:
            return self.texts(module.constants[name], Scope(module, None), active)
        imported = module.imports.get(name)
        if imported is not None and imported[1] is not None and imported[0] in self.modules:
            return self._name(imported[1], Scope(self.modules[imported[0]], None), active)
        raise UnresolvedError(f"{name} is not a literal, a module constant or a local assignment")

    def _bound(
        self,
        name: str,
        bindings: Sequence[_Binding],
        scope: Scope,
        active: frozenset[tuple[int, str]],
    ) -> tuple[str, ...]:
        values: list[str] = []
        appended: list[ast.expr] = []
        for binding in bindings:
            if binding.kind == "value":
                values += self.texts(binding.node, scope, active)
            elif binding.kind == "item":
                values.append(self._item(binding.node, binding.index, scope))
            elif binding.kind == "each":
                values += self.names(binding.node, scope)
            else:
                appended.append(binding.node)
        if not values:
            raise UnresolvedError(f"{name} is only ever appended to")
        for node in appended:
            suffixes = self.texts(node, scope, active)
            values += [value + suffix for value in values for suffix in suffixes]
        return _unique(values)

    # app.core.sql

    def _module_alias(self, name: str, scope: Scope) -> Module | None:
        imported = scope.module.imports.get(name)
        if imported is None or imported[1] is not None:
            return None
        return self.modules.get(imported[0])

    def _sql_helper(self, call: ast.Call, scope: Scope) -> str:
        func = call.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = self._module_alias(func.value.id, scope)
            if module is not None and module.name == _SQL_MODULE:
                return func.attr
        elif isinstance(func, ast.Name):
            imported = scope.module.imports.get(func.id)
            if imported is not None and imported[0] == _SQL_MODULE and imported[1]:
                return imported[1]
        raise UnresolvedError(f"{ast.unparse(call)} is not a helper of app/core/sql.py")

    def _call(
        self, call: ast.Call, scope: Scope, active: frozenset[tuple[int, str]]
    ) -> tuple[str, ...]:
        try:
            return self._helper_texts(call, scope, active)
        except ValueError as exc:  # the helper refuses what it would refuse at run time
            raise UnresolvedError(f"{ast.unparse(call)}: {exc}") from exc

    def _helper_texts(
        self, call: ast.Call, scope: Scope, active: frozenset[tuple[int, str]]
    ) -> tuple[str, ...]:
        helper = self._sql_helper(call, scope)
        arguments = call.args
        if helper == "identifier" and len(arguments) == 2:
            allowed = self.names(arguments[1], scope)
            try:
                chosen = self.texts(arguments[0], scope, active)
            except UnresolvedError:
                return allowed
            return tuple(sql.identifier(name, allowed) for name in chosen)
        if helper == "where" and len(arguments) == 2:
            filters = self.filters(arguments[0], scope)
            selections = self._selections(arguments[1])
            if selections is None:
                selections = [(), *((name,) for name, _ in filters)]
            return _unique([sql.where(filters, selection) for selection in selections])
        if helper == "assignments" and len(arguments) == 2:
            allowed = self.names(arguments[1], scope)
            return (sql.assignments(allowed, allowed),)
        if helper == "column_list":
            return self._column_list(call, scope, active)
        raise UnresolvedError(f"{ast.unparse(call)} is not expanded by this check")

    def _column_list(
        self, call: ast.Call, scope: Scope, active: frozenset[tuple[int, str]]
    ) -> tuple[str, ...]:
        """``sql.column_list(columns, table, prefix)``: the columns, with each alias and prefix."""
        parameters = ("columns", "table", "prefix")
        if len(call.args) > len(parameters):
            raise UnresolvedError(f"{ast.unparse(call)} has more arguments than column_list takes")
        given = dict(zip(parameters, call.args, strict=False))
        for keyword in call.keywords:
            if keyword.arg not in parameters or keyword.arg in given:
                raise UnresolvedError(f"{ast.unparse(call)} names an argument twice or unknown")
            given[keyword.arg] = keyword.value
        if "columns" not in given:
            raise UnresolvedError(f"{ast.unparse(call)} names no columns")
        columns = self.names(given["columns"], scope)
        tables = self.texts(given["table"], scope, active) if "table" in given else ("",)
        prefixes = self.texts(given["prefix"], scope, active) if "prefix" in given else ("",)
        return _unique(
            [
                sql.column_list(columns, table, prefix)
                for table, prefix in itertools.product(tables, prefixes)
            ]
        )

    def _item(self, node: ast.expr, index: int, scope: Scope) -> str:
        if (
            isinstance(node, ast.Call)
            and self._sql_helper(node, scope) == "insert_columns"
            and len(node.args) == 2
        ):
            allowed = self.names(node.args[1], scope)
            return sql.insert_columns(allowed, allowed)[index]
        raise UnresolvedError(f"{ast.unparse(node)} is unpacked, which only insert_columns may be")

    def _constant(self, expr: ast.expr, scope: Scope) -> tuple[ast.expr, Scope]:
        """Follow a name to the literal it stands for (module constants and imports only)."""
        seen: set[tuple[str, str]] = set()
        while True:
            if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
                module = self._module_alias(expr.value.id, scope)
                if module is None:
                    break
                expr, scope = ast.Name(id=expr.attr), Scope(module, None)
                continue
            if not isinstance(expr, ast.Name):
                return expr, scope
            if (scope.module.name, expr.id) in seen:
                break
            seen.add((scope.module.name, expr.id))
            module = scope.module
            if expr.id in module.constants:
                expr, scope = module.constants[expr.id], Scope(module, None)
                continue
            imported = module.imports.get(expr.id)
            if imported is None or imported[1] is None or imported[0] not in self.modules:
                break
            expr, scope = ast.Name(id=imported[1]), Scope(self.modules[imported[0]], None)
        raise UnresolvedError(f"{ast.unparse(expr)} is not a module-level tuple of literals")

    def names(self, expr: ast.expr, scope: Scope) -> tuple[str, ...]:
        """A tuple of string literals (``*OTHER`` included): an allowlist or a row's columns."""
        literal, scope = self._constant(expr, scope)
        if isinstance(literal, ast.Tuple | ast.List):
            names: list[str] = []
            for element in literal.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    names.append(element.value)
                elif isinstance(element, ast.Starred):
                    names += self.names(element.value, scope)
                else:
                    break
            else:
                return tuple(names)
        raise UnresolvedError(f"{ast.unparse(expr)} is not a tuple of string literals")

    def filters(self, expr: ast.expr, scope: Scope) -> sql.Filters:
        literal, _ = self._constant(expr, scope)
        if isinstance(literal, ast.Tuple):
            pairs = [_literal_pair(element) for element in literal.elts]
            if all(pairs):
                return tuple(pair for pair in pairs if pair)
        raise UnresolvedError(f"{ast.unparse(expr)} is not a tuple of (name, fragment) literals")

    def _selections(self, expr: ast.expr) -> list[tuple[str, ...]] | None:
        """The literal filter selections of a ``sql.where`` call, or None when they are computed."""
        if isinstance(expr, ast.IfExp):
            body, orelse = self._selections(expr.body), self._selections(expr.orelse)
            return None if body is None or orelse is None else body + orelse
        if isinstance(expr, ast.List | ast.Tuple):
            names = [
                element.value
                for element in expr.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            return [tuple(names)] if len(names) == len(expr.elts) else None
        return None


def _literal_pair(element: ast.expr) -> tuple[str, str] | None:
    match element:
        case ast.Tuple(elts=[ast.Constant(value=str() as name), ast.Constant(value=str() as text)]):
            return name, text
        case _:
            return None


# --- finding ------------------------------------------------------------------------------------


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> tuple[Function | None, str]:
    function: Function | None = None
    names: list[str] = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            function = function or current
            names.append(current.name)
        elif isinstance(current, ast.ClassDef):
            names.append(current.name)
        current = parents.get(current)
    return function, ".".join(reversed(names)) or "<module>"


def _is_part(parent: ast.AST | None) -> bool:
    """Part of a larger text (an f-string, a ``+``) or a bare string such as a docstring."""
    if isinstance(parent, ast.JoinedStr | ast.FormattedValue | ast.Expr):
        return True
    return isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add)


def _operands(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _operands(node.left) + _operands(node.right)
    return [node]


class Finder:
    def __init__(self, modules: Mapping[str, Module]) -> None:
        self.modules = modules
        self.resolver = Resolver(modules)

    def _head(self, node: ast.expr, scope: Scope) -> str | None:
        """The text with each variable part as ``_``; a leading variable part is resolved."""
        pieces: list[str] = []
        for operand in _operands(node):
            for value in operand.values if isinstance(operand, ast.JoinedStr) else [operand]:
                if isinstance(value, ast.Constant):
                    if not isinstance(value.value, str):
                        return None
                    pieces.append(value.value)
                elif pieces:
                    pieces.append("_")
                else:
                    expr = value.value if isinstance(value, ast.FormattedValue) else value
                    try:
                        pieces.append(self.resolver.texts(expr, scope)[0])
                    except UnresolvedError:
                        return None
        return "".join(pieces)

    def _statement(self, node: ast.expr, scope: Scope, location: tuple[str, int, str]) -> Statement:
        parts: list[str | int] = []
        labels: list[str] = []
        expressions: list[ast.expr] = []

        def add(expr: ast.expr) -> None:
            if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                parts.append(expr.value)
                return
            if isinstance(expr, ast.FormattedValue):
                if expr.conversion != -1 or expr.format_spec is not None:
                    raise UnresolvedError(f"{ast.unparse(expr.value)} is formatted, not inserted")
                expr = expr.value
            label = expr.id if isinstance(expr, ast.Name) else ast.unparse(expr)
            if label not in labels:
                labels.append(label)
                expressions.append(expr)
            parts.append(labels.index(label))

        for operand in _operands(node):
            if isinstance(operand, ast.JoinedStr):
                for value in operand.values:
                    add(value)
            else:
                add(operand)
        slots = tuple(
            Slot(label, self.resolver.texts(expr, scope))
            for label, expr in zip(labels, expressions, strict=True)
        )
        path, line, function = location
        return Statement(path, line, function, tuple(parts), slots)

    def find(self) -> tuple[list[Statement], list[str], int]:
        """The statements, the sites that cannot be expanded, and how many exceptions were used."""
        statements: list[Statement] = []
        problems: list[str] = []
        used: set[tuple[str, str]] = set()
        for module in self.modules.values():
            if module.name.startswith(_GENERATED_PACKAGE):
                continue
            parents = _parents(module.tree)
            for node in ast.walk(module.tree):
                if not isinstance(node, ast.Constant | ast.JoinedStr | ast.BinOp):
                    continue
                if _is_part(parents.get(node)):
                    continue
                function, qualname = _enclosing(node, parents)
                scope = Scope(module, function)
                head = self._head(node, scope)
                if head is None or not _STATEMENT.match(head):
                    continue
                location = (module.path, node.lineno, qualname)
                try:
                    statement = self._statement(node, scope, location)
                except UnresolvedError as exc:
                    if (module.path, qualname) in EXCEPTIONS:
                        used.add((module.path, qualname))
                        continue
                    problems.append(
                        f"{module.path}:{node.lineno}: cannot expand: {exc}; build it from"
                        " app/core/sql.py helpers or list the site in"
                        " tools/dbgen/sqlcheck.py EXCEPTIONS with its reason"
                    )
                    continue
                if statement.size() > MAX_COMBINATIONS:
                    problems.append(
                        f"{statement.location}: {statement.size()} combinations; split the"
                        " statement so each part varies less"
                    )
                    continue
                statements.append(statement)
        problems += [
            f"{path}: {function}() is in EXCEPTIONS but has no statement that needs it"
            for path, function in sorted(set(EXCEPTIONS) - used)
        ]
        return statements, problems, len(used)


# --- checking -----------------------------------------------------------------------------------


class _Null(dict[str, None]):
    """Binds every named parameter to NULL."""

    def __missing__(self, key: str) -> None:
        return None


def compile_error(databases: Mapping[str, sqlite3.Connection], text: str) -> str | None:
    """None when one of the databases compiles ``text``, else SQLite's most telling message."""
    statement = _EXPANDING_IN.sub(r"IN (:\1)", text)
    errors: list[tuple[str, str]] = []
    for name, database in databases.items():
        try:
            database.execute(f"EXPLAIN {statement}", _Null())
        except sqlite3.Error as exc:
            errors.append((name, str(exc)))
        else:
            return None
    # "no such table" from the other database says only that the statement is not for it.
    telling = [error for error in errors if not error[1].startswith("no such table")] or errors
    return "; ".join(f"{name}: {message}" for name, message in telling)


def check(statement: Statement, databases: Mapping[str, sqlite3.Connection]) -> list[Failure]:
    results = {
        choice: compile_error(databases, statement.render(choice))
        for choice in statement.choices()
    }
    passed = [choice for choice, error in results.items() if error is None]
    failures: dict[str, Failure] = {}

    def fail(choice: tuple[int, ...]) -> None:
        text = statement.render(choice)
        failures.setdefault(text, Failure(statement.location, text, results[choice] or ""))

    if not passed:
        fail(next(iter(results)))
        return list(failures.values())
    for index, slot in enumerate(statement.slots):
        for alternative in range(len(slot.alternatives)):
            if not any(choice[index] == alternative for choice in passed):
                fail(next(choice for choice in results if choice[index] == alternative))
    return list(failures.values())
