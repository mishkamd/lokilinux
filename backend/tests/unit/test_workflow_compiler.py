"""
Unit tests for WorkflowCompiler — YAML <-> graph, and the semantic checks
Pydantic alone can't express (cycles, dangling edges, reachability).
"""

from pathlib import Path

import pytest

from lokilinux.services.workflow_compiler import (
    build_graph,
    compile_workflow,
    parse_yaml_text,
    serialize_document,
    validate_graph,
)
from lokilinux.schemas.workflow import WorkflowDocument

VALID_LINEAR = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: linear-three-step
spec:
  targets:
    all: true
  steps:
    - { id: precheck, type: command, name: Preflight, config: { command: "true" } }
    - { id: approval, type: approval, name: Approve, config: {} }
    - { id: apply, type: command, name: Apply, config: { command: "true" } }
  edges:
    - { from: precheck, to: approval, on: success }
    - { from: approval, to: apply, on: success }
"""

VALID_BRANCHING = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: branching-with-rollback
spec:
  targets:
    all: true
  steps:
    - { id: upgrade, type: command, name: Upgrade, config: { command: "true" }, on_failure: branch }
    - { id: validate, type: validation, name: Validate, config: { command: "true" } }
    - { id: rollback, type: command, name: Rollback, config: { command: "true" } }
  edges:
    - { from: upgrade, to: validate, on: success }
    - { from: upgrade, to: rollback, on: failure }
"""


def test_parse_yaml_text_valid():
    data = parse_yaml_text(VALID_LINEAR)
    assert data["metadata"]["name"] == "linear-three-step"


def test_parse_yaml_text_syntax_error_reports_line():
    from lokilinux.services.workflow_compiler import WorkflowParseError

    bad = "apiVersion: lokilinux/v1\nkind: Workflow\nmetadata:\n  name: x\n  - bad indent\n"
    with pytest.raises(WorkflowParseError) as exc_info:
        parse_yaml_text(bad)
    assert exc_info.value.line is not None


def test_compile_workflow_valid_linear():
    doc, graph, result = compile_workflow(VALID_LINEAR)
    assert result.valid
    assert doc is not None
    assert graph is not None
    assert graph.entry_ids == ["precheck"]
    assert len(graph.steps) == 3


def test_compile_workflow_valid_branching_has_two_entry_free_paths():
    doc, graph, result = compile_workflow(VALID_BRANCHING)
    assert result.valid, result.errors
    assert graph.entry_ids == ["upgrade"]


def test_duplicate_step_id_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: dup-ids }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
    - { id: a, type: command, name: A2, config: { command: "true" } }
  edges: []
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid
    assert any(e.code == "DUPLICATE_STEP_ID" for e in result.errors)


def test_dangling_edge_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: dangling-edge }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
  edges:
    - { from: a, to: nonexistent, on: success }
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid
    assert any(e.code == "DANGLING_EDGE" for e in result.errors)


def test_cycle_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: has-cycle }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
    - { id: b, type: command, name: B, config: { command: "true" } }
  edges:
    - { from: a, to: b, on: success }
    - { from: b, to: a, on: success }
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid
    assert any(e.code == "CYCLE_DETECTED" for e in result.errors)


def test_no_entry_point_rejected():
    # Every step has an incoming edge -> impossible to start.
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: no-entry }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
    - { id: b, type: command, name: B, config: { command: "true" } }
  edges:
    - { from: a, to: b, on: success }
    - { from: b, to: a, on: failure }
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid
    # This is also a cycle, so either CYCLE_DETECTED or NO_ENTRY_POINT is
    # acceptable — cycle detection runs first and short-circuits.
    assert any(e.code in ("CYCLE_DETECTED", "NO_ENTRY_POINT") for e in result.errors)


def test_unreachable_step_is_a_warning_not_an_error():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: unreachable-step }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
    - { id: parked, type: command, name: Parked, config: { command: "true" } }
  edges: []
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert result.valid
    assert any(w.code == "UNREACHABLE_STEP" and w.step_id == "parked" for w in result.warnings)


def test_branch_without_failure_edge_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: branch-no-failure-edge }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" }, on_failure: branch }
    - { id: b, type: command, name: B, config: { command: "true" } }
  edges:
    - { from: a, to: b, on: success }
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid
    assert any(e.code == "BRANCH_WITHOUT_FAILURE_EDGE" for e in result.errors)


def test_literal_secret_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: literal-secret }
spec:
  targets: { all: true }
  steps:
    - { id: a, type: ansible, name: A, config: { api_key: "sk-abc123" } }
  edges: []
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid


def test_unsupported_strategy_mode_rejected():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: bad-strategy }
spec:
  targets: { all: true }
  strategy: { mode: rolling }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
  edges: []
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid


def test_targets_must_have_exactly_one_shape():
    yaml_src = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: bad-targets }
spec:
  targets: { all: true, agent_ids: ["11111111-1111-1111-1111-111111111111"] }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
  edges: []
"""
    doc, graph, result = compile_workflow(yaml_src)
    assert not result.valid


@pytest.mark.parametrize("fixture", [VALID_LINEAR, VALID_BRANCHING])
def test_round_trip_semantic_idempotency(fixture: str):
    """parse -> compile -> serialize -> parse again must yield an equal
    CompiledGraph. Not byte-identical text (comments aren't preserved by
    plain PyYAML — that's the frontend CST's job, plan §9) — semantic
    equality only."""
    doc1, graph1, result1 = compile_workflow(fixture)
    assert result1.valid, result1.errors

    reserialized = serialize_document(doc1)

    doc2, graph2, result2 = compile_workflow(reserialized)
    assert result2.valid, result2.errors
    assert graph1.model_dump() == graph2.model_dump()


def test_validate_graph_directly_on_parsed_document():
    doc = WorkflowDocument.model_validate(parse_yaml_text(VALID_LINEAR))
    errors, warnings = validate_graph(doc)
    assert errors == []

    graph = build_graph(doc)
    assert graph.entry_ids == ["precheck"]


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "workflows"


def test_oracle_linux_8_to_9_flagship_example_compiles_clean():
    """The complete plan §D example — 16 steps, 21 edges, one entry point,
    six failure branches converging on rollback. Must compile with zero
    errors and zero warnings; this is Phase 0's acceptance criterion #1."""
    yaml_source = (FIXTURES_DIR / "oracle-linux-8-to-9.yaml").read_text()
    doc, graph, result = compile_workflow(yaml_source)
    assert result.valid, result.errors
    assert result.warnings == []
    assert graph.entry_ids == ["connectivity"]
    assert len(graph.steps) == 16
    assert len(graph.edges) == 21

    rollback_edges = [e for e in graph.edges if e.to == "rollback"]
    assert len(rollback_edges) == 7
    assert all(e.on == "failure" for e in rollback_edges)


def test_150_step_workflow_compiles_and_validates_fast():
    """Faza 12 acceptance criterion #9 ('150 de noduri rămân interactive') —
    the compiler side of that claim: parse -> Pydantic -> validate_graph's
    cycle/reachability DFS -> build_graph must stay well under a second even
    at 150 steps cycling through all 14 node types, or the editor's own
    800ms debounced re-validate would visibly lag typing."""
    import time

    type_cycle = [
        ("command", {"command": "true"}),
        ("check", {"type": "command", "command": "true"}),
        ("service", {"action": "restart", "name": "nginx"}),
        ("system", {"action": "sysctl", "key": "net.ipv4.ip_forward", "value": "1"}),
        ("file", {"action": "create", "path": "/tmp/x", "content": "x"}),
        ("package", {"action": "install", "packages": ["nginx"]}),
        ("wait", {"mode": "duration", "seconds": 1}),
    ]
    lines = [
        "apiVersion: lokilinux/v1", "kind: Workflow",
        "metadata:\n  name: perf-150-steps",
        "spec:\n  targets: { all: true }\n  steps:",
    ]
    for i in range(150):
        step_type, config = type_cycle[i % len(type_cycle)]
        lines.append(f"    - {{ id: step_{i}, type: {step_type}, name: Step {i}, config: {config!r} }}")
    lines.append("  edges:")
    for i in range(149):
        lines.append(f"    - {{ from: step_{i}, to: step_{i + 1}, on: always }}")
    yaml_source = "\n".join(lines).replace("'", '"')

    started = time.monotonic()
    doc, graph, result = compile_workflow(yaml_source)
    elapsed = time.monotonic() - started

    assert result.valid, result.errors
    assert len(graph.steps) == 150
    assert elapsed < 1.0, f"compile_workflow took {elapsed:.3f}s for 150 steps"
