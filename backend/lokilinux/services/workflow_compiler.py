"""
WorkflowCompiler: YAML <-> graph, plus the semantic validation the Pydantic
schema alone can't express (cycles, dangling edges, reachability).

yaml_source is authoritative for humans and Git; `graph` (CompiledGraph) is
what the engine reads (workflow_engine.py) so it never re-parses YAML per
tick — see models/workflow.py's WorkflowVersion docstring.

Comment-preserving surgical edits (moving a node only touches `layout:`) are
a client-side concern (plan §9, the `yaml` npm package's CST) — this module
uses plain PyYAML and is not round-trip-formatting-preserving. Its own
round-trip guarantee is semantic: parse -> compile -> serialize -> parse
again must yield an equal CompiledGraph (tests/unit/test_workflow_compiler.py).
"""

import hashlib

import yaml
from pydantic import ValidationError

# PyYAML's SafeLoader follows YAML 1.1, which resolves bare `on`/`off`/`yes`/
# `no` (any case) as booleans — fatal here since edges use `on: failure` as
# a literal mapping key: PyYAML would silently turn it into `True: failure`,
# and the `on` field would never be populated from that entry. This is a
# well-known PyYAML gotcha; the fix restricts the bool resolver to YAML
# 1.2's true/false only, which also matches how a human reads this schema.
class _WorkflowYamlLoader(yaml.SafeLoader):
    pass


_WorkflowYamlLoader.yaml_implicit_resolvers = {
    first_char: [
        (tag, regexp) for tag, regexp in resolvers
        if not (tag == "tag:yaml.org,2002:bool" and first_char in "oOyYnN")
    ]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

from lokilinux.schemas.workflow import (
    CompiledGraph,
    ValidationIssue,
    ValidationResult,
    WorkflowDocument,
    WorkflowNodeType,
)
from lokilinux.utils.expr import validate_expression


class WorkflowParseError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


def parse_yaml_text(yaml_source: str) -> dict:
    """Raw YAML -> dict. Raises WorkflowParseError with 1-indexed line/column
    on malformed YAML (mirrors the "YAML Parse Error / Line 24 / Unexpected
    indentation" shape called for in the brief)."""
    try:
        data = yaml.load(yaml_source, Loader=_WorkflowYamlLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        column = mark.column + 1 if mark else None
        message = getattr(exc, "problem", None) or str(exc)
        raise WorkflowParseError(message, line=line, column=column) from exc
    if not isinstance(data, dict):
        raise WorkflowParseError("Document must be a YAML mapping at the top level")
    return data


def compute_content_hash(yaml_source: str) -> str:
    return hashlib.sha256(yaml_source.encode("utf-8")).hexdigest()


def compile_workflow(yaml_source: str) -> tuple[WorkflowDocument | None, CompiledGraph | None, ValidationResult]:
    """The one entry point routers/workers should call. Returns
    (document, graph, result) — document/graph are None when result.valid
    is False."""
    try:
        data = parse_yaml_text(yaml_source)
    except WorkflowParseError as exc:
        issue = ValidationIssue(code="YAML_SYNTAX", message=exc.message, path="$", line=exc.line, column=exc.column)
        return None, None, ValidationResult(valid=False, errors=[issue])

    try:
        doc = WorkflowDocument.model_validate(data)
    except ValidationError as exc:
        errors = [
            ValidationIssue(
                code="SCHEMA_" + "_".join(str(p).upper() for p in e["loc"][:1]) if e["loc"] else "SCHEMA",
                message=e["msg"],
                path=".".join(str(p) for p in e["loc"]) or "$",
            )
            for e in exc.errors()
        ]
        return None, None, ValidationResult(valid=False, errors=errors)

    errors, warnings = validate_graph(doc)
    if errors:
        return doc, None, ValidationResult(valid=False, errors=errors, warnings=warnings)

    graph = build_graph(doc)
    return doc, graph, ValidationResult(valid=True, warnings=warnings)


def validate_graph(doc: WorkflowDocument) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Everything Pydantic's per-field validators can't see: relationships
    between steps and edges. Returns (errors, warnings)."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    steps = doc.spec.steps
    edges = doc.spec.edges
    step_ids = [s.id for s in steps]

    # Duplicate step ids
    seen: set[str] = set()
    for i, sid in enumerate(step_ids):
        if sid in seen:
            errors.append(ValidationIssue(
                code="DUPLICATE_STEP_ID", message=f"Step id '{sid}' is declared twice",
                path=f"spec.steps[{i}].id", step_id=sid,
            ))
        seen.add(sid)

    # Dangling edges
    valid_ids = set(step_ids)
    adjacency: dict[str, list] = {sid: [] for sid in valid_ids}
    incoming: dict[str, int] = {sid: 0 for sid in valid_ids}
    for i, e in enumerate(edges):
        if e.from_ not in valid_ids:
            errors.append(ValidationIssue(
                code="DANGLING_EDGE", message=f"Edge source '{e.from_}' has no matching step",
                path=f"spec.edges[{i}].from",
            ))
        if e.to not in valid_ids:
            errors.append(ValidationIssue(
                code="DANGLING_EDGE", message=f"Edge target '{e.to}' has no matching step",
                path=f"spec.edges[{i}].to",
            ))
        if e.from_ in valid_ids and e.to in valid_ids:
            adjacency[e.from_].append((e.to, e.on))
            incoming[e.to] += 1

    if errors:
        # Cycle/reachability analysis assumes a well-formed edge list —
        # bail before it, same reasoning as the client-side Level 1 check.
        return errors, warnings

    # Cycle detection — DFS with 3-color marking
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {sid: WHITE for sid in valid_ids}
    cycle_step: str | None = None

    def _dfs(node: str) -> bool:
        nonlocal cycle_step
        color[node] = GRAY
        for target, _on in adjacency[node]:
            if color[target] == GRAY:
                cycle_step = target
                return True
            if color[target] == WHITE and _dfs(target):
                return True
        color[node] = BLACK
        return False

    for sid in valid_ids:
        if color[sid] == WHITE and _dfs(sid):
            errors.append(ValidationIssue(
                code="CYCLE_DETECTED", message=f"Step '{cycle_step}' is part of a cycle — workflows must be a DAG",
                path="spec.edges", step_id=cycle_step,
            ))
            break

    if errors:
        return errors, warnings

    # Entry points — steps with no incoming edge
    entry_ids = [sid for sid in step_ids if incoming[sid] == 0]
    if not entry_ids:
        errors.append(ValidationIssue(
            code="NO_ENTRY_POINT", message="Every step has an incoming edge — a workflow needs at least one entry point",
            path="spec.edges",
        ))
        return errors, warnings

    # Orphan detection — a step with no edges at all (neither incoming nor
    # outgoing) will never run and was almost certainly meant to be wired
    # in. NOT the same as "unreachable from the union of all entry points":
    # in an acyclic graph every node has a path back to some in-degree-0
    # node, and forward BFS from every entry point covers the whole graph
    # by construction — so that check can never actually fire. A step with
    # incoming==0 is instead a legitimate additional entry point.
    if len(step_ids) > 1:
        for sid in step_ids:
            if incoming[sid] == 0 and not adjacency[sid]:
                warnings.append(ValidationIssue(
                    code="UNREACHABLE_STEP", message=f"Step '{sid}' has no connections — it will never run",
                    path=f"spec.steps.{sid}", step_id=sid,
                ))

    # condition steps: expression must parse and stay within the AST
    # whitelist — rejected here at publish (plan §13 Level 3), never
    # deferred to a runtime failure mid-run (utils/expr.py).
    for step in steps:
        if step.type != WorkflowNodeType.CONDITION:
            continue
        expression = step.config.get("expression")
        if not expression:
            errors.append(ValidationIssue(
                code="CONDITION_MISSING_EXPRESSION", message=f"Step '{step.id}' (type condition) has no config.expression",
                path=f"spec.steps.{step.id}.config.expression", step_id=step.id,
            ))
            continue
        expr_error = validate_expression(str(expression))
        if expr_error:
            errors.append(ValidationIssue(
                code="CONDITION_INVALID_EXPRESSION", message=f"Step '{step.id}': {expr_error}",
                path=f"spec.steps.{step.id}.config.expression", step_id=step.id,
            ))

    # branch steps must have a reachable on: failure edge somewhere downstream
    for step in steps:
        if step.on_failure == "branch":
            has_failure_edge = any(on == "failure" for _target, on in adjacency.get(step.id, []))
            if not has_failure_edge:
                errors.append(ValidationIssue(
                    code="BRANCH_WITHOUT_FAILURE_EDGE",
                    message=f"Step '{step.id}' has on_failure: branch but no outgoing edge with on: failure",
                    path=f"spec.steps.{step.id}.on_failure", step_id=step.id,
                ))

    errors.extend(_validate_step_configs(steps))

    return errors, warnings


_LEGACY_ALIASES = {
    WorkflowNodeType.VALIDATION: WorkflowNodeType.CHECK,
    WorkflowNodeType.WAIT_FOR_AGENT: WorkflowNodeType.WAIT,
}
_SERVICE_ACTIONS = ("start", "stop", "restart", "reload", "enable", "disable")
_SYSTEM_ACTIONS = ("reboot", "shutdown", "hostname", "timezone", "sysctl")
_FILE_ACTIONS = ("create", "template", "delete", "copy", "chmod", "chown")
_PACKAGE_ACTIONS = ("install", "update", "remove")  # downgrade rejected below
_CHECK_TYPES = ("command", "service", "port", "package", "file", "process", "os", "disk", "network")
_WAIT_MODES = ("agent", "duration")  # 'condition' rejected below


def _cfg_error(step, key: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=f"spec.steps.{step.id}.config.{key}", step_id=step.id)


def _require_field(step, config: dict, key: str, errors: list[ValidationIssue]) -> None:
    if not config.get(key):
        errors.append(_cfg_error(step, key, "MISSING_REQUIRED_FIELD", f"Step '{step.id}': config.{key} is required"))


def _validate_step_configs(steps) -> list[ValidationIssue]:
    """Publish-time (Level 3) checks for the Linux/Check/Wait node types —
    the same fields _dispatch_step/_require enforce at runtime, caught here
    instead so a broken step never reaches an actual run (plan §13)."""
    errors: list[ValidationIssue] = []

    for step in steps:
        normalized = _LEGACY_ALIASES.get(step.type, step.type)
        config = step.config or {}

        if normalized == WorkflowNodeType.SERVICE:
            action = config.get("action")
            if action not in _SERVICE_ACTIONS:
                errors.append(_cfg_error(step, "action", "INVALID_ACTION", f"Step '{step.id}': action must be one of {_SERVICE_ACTIONS}"))
            _require_field(step, config, "name", errors)

        elif normalized == WorkflowNodeType.SYSTEM:
            action = config.get("action")
            if action not in _SYSTEM_ACTIONS:
                errors.append(_cfg_error(step, "action", "INVALID_ACTION", f"Step '{step.id}': action must be one of {_SYSTEM_ACTIONS}"))
            elif action in ("hostname", "timezone"):
                _require_field(step, config, "value", errors)
            elif action == "sysctl":
                _require_field(step, config, "key", errors)
                _require_field(step, config, "value", errors)

        elif normalized == WorkflowNodeType.FILE:
            action = config.get("action")
            if action not in _FILE_ACTIONS:
                errors.append(_cfg_error(step, "action", "INVALID_ACTION", f"Step '{step.id}': action must be one of {_FILE_ACTIONS}"))
            _require_field(step, config, "path", errors)
            if action == "copy":
                _require_field(step, config, "source", errors)

        elif normalized == WorkflowNodeType.PACKAGE:
            action = config.get("action") or "install"
            if action == "downgrade":
                errors.append(_cfg_error(step, "action", "UNSUPPORTED_ACTION", f"Step '{step.id}': package action 'downgrade' is not supported yet"))
            elif action not in _PACKAGE_ACTIONS:
                errors.append(_cfg_error(step, "action", "INVALID_ACTION", f"Step '{step.id}': action must be one of {_PACKAGE_ACTIONS}"))
            elif action == "remove" and not config.get("packages"):
                errors.append(_cfg_error(step, "packages", "MISSING_REQUIRED_FIELD", f"Step '{step.id}': config.packages must be a non-empty list"))

        elif normalized == WorkflowNodeType.CHECK:
            check_type = config.get("type") or "command"
            if check_type not in _CHECK_TYPES:
                errors.append(_cfg_error(step, "type", "INVALID_CHECK_TYPE", f"Step '{step.id}': check type must be one of {_CHECK_TYPES}"))
            elif check_type in ("command",):
                _require_field(step, config, "command", errors)
            elif check_type in ("service", "process"):
                _require_field(step, config, "name" if check_type == "process" else "service", errors)
            elif check_type == "port":
                _require_field(step, config, "port", errors)
            elif check_type == "package":
                _require_field(step, config, "name", errors)
            elif check_type == "file":
                _require_field(step, config, "path", errors)
            elif check_type == "os":
                _require_field(step, config, "distro", errors)
            elif check_type == "disk":
                _require_field(step, config, "min_free_gb", errors)
            elif check_type == "network":
                _require_field(step, config, "host", errors)

        elif normalized == WorkflowNodeType.WAIT:
            mode = config.get("mode") or "agent"
            if mode == "condition":
                errors.append(_cfg_error(step, "mode", "UNSUPPORTED_MODE", f"Step '{step.id}': wait mode 'condition' is not supported yet"))
            elif mode not in _WAIT_MODES:
                errors.append(_cfg_error(step, "mode", "INVALID_MODE", f"Step '{step.id}': mode must be one of {_WAIT_MODES + ('condition',)}"))

    return errors


def build_graph(doc: WorkflowDocument) -> CompiledGraph:
    """Assumes validate_graph already returned no errors for this document."""
    incoming = {s.id: 0 for s in doc.spec.steps}
    for e in doc.spec.edges:
        if e.to in incoming:
            incoming[e.to] += 1
    entry_ids = [s.id for s in doc.spec.steps if incoming[s.id] == 0]

    return CompiledGraph(
        targets=doc.spec.targets,
        strategy=doc.spec.strategy,
        defaults=doc.spec.defaults,
        vars=doc.spec.vars,
        steps=doc.spec.steps,
        edges=doc.spec.edges,
        entry_ids=entry_ids,
        layout=doc.layout,
    )


def serialize_document(doc: WorkflowDocument) -> str:
    """Document -> YAML text. Used where a workflow originates from Python
    objects rather than user-typed YAML — the Policy importer (plan §15
    stage B) and this module's own round-trip tests. Not comment-preserving;
    see module docstring."""
    payload = doc.model_dump(mode="json", by_alias=True, exclude_none=True)
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
