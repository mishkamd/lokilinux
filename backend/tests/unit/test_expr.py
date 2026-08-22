"""
Unit tests for the restricted condition-expression evaluator (utils/expr.py,
plan Partea I §18) — "every rejected form gets its own test: import, call,
lambda, comprehension, attribute outside context."
"""

import pytest

from lokilinux.utils.expr import ExpressionError, evaluate_condition, validate_expression

CONTEXT = {
    "steps": {
        "upgrade": {"status": "SUCCEEDED", "exit_code": 0, "duration_seconds": 12.5},
        "precheck": {"status": "FAILED", "exit_code": 1, "duration_seconds": 3.0},
    },
    "vars": {"threshold": 5, "name": "prod"},
    "targets": {"count": 12},
}


class TestValidExpressions:
    def test_simple_status_comparison(self):
        assert evaluate_condition("steps.upgrade.status == 'SUCCEEDED'", CONTEXT) is True

    def test_status_inequality(self):
        assert evaluate_condition("steps.precheck.status != 'SUCCEEDED'", CONTEXT) is True

    def test_numeric_comparison(self):
        assert evaluate_condition("steps.upgrade.exit_code == 0", CONTEXT) is True
        assert evaluate_condition("vars.threshold > 10", CONTEXT) is False

    def test_boolean_and_or(self):
        assert evaluate_condition(
            "steps.upgrade.status == 'SUCCEEDED' and steps.precheck.status == 'FAILED'", CONTEXT,
        ) is True
        assert evaluate_condition("vars.threshold > 10 or targets.count > 5", CONTEXT) is True

    def test_not_operator(self):
        assert evaluate_condition("not (steps.upgrade.status == 'FAILED')", CONTEXT) is True

    def test_subscript_access(self):
        assert evaluate_condition("steps['upgrade']['status'] == 'SUCCEEDED'", CONTEXT) is True

    def test_targets_count(self):
        assert evaluate_condition("targets.count >= 12", CONTEXT) is True

    def test_string_membership(self):
        assert evaluate_condition("vars.name in 'production'", CONTEXT) is True

    def test_bool_coercion_of_non_bool_result(self):
        # A truthy/falsy non-bool result (e.g. a bare string) still coerces —
        # evaluate_condition always returns a real bool, never the raw value.
        assert evaluate_condition("vars.name", CONTEXT) is True


class TestRejectedConstructs:
    """Each disallowed form gets its own test — a single parametrized case
    would hide which specific construct started passing if the whitelist
    ever regressed."""

    def test_function_call_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("len(vars.name) > 0", CONTEXT)

    def test_import_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("__import__('os').system('echo hi')", CONTEXT)

    def test_lambda_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("(lambda: True)()", CONTEXT)

    def test_list_comprehension_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("[x for x in [1,2,3]]", CONTEXT)

    def test_dunder_attribute_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("steps.__class__", CONTEXT)

    def test_dunder_class_escape_chain_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("steps.__class__.__bases__[0].__subclasses__()", CONTEXT)

    def test_underscore_prefixed_name_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("_secret", CONTEXT)

    def test_assignment_via_walrus_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("(x := 5) > 0", CONTEXT)

    def test_attribute_outside_context_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("steps.nonexistent_step.status == 'SUCCEEDED'", CONTEXT)

    def test_unknown_top_level_name_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("unknown_name == 1", CONTEXT)

    def test_syntax_error_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("steps.upgrade.status ==", CONTEXT)

    def test_starred_expression_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("*[1, 2]", CONTEXT)

    def test_fstring_rejected(self):
        with pytest.raises(ExpressionError):
            evaluate_condition("f'{vars.name}'", CONTEXT)


class TestValidateExpression:
    """The publish-time check (workflow_compiler.py) — must reject at
    publish, not wait for a runtime failure mid-run (plan §13 Level 3)."""

    def test_valid_expression_returns_none(self):
        assert validate_expression("steps.upgrade.status == 'SUCCEEDED'") is None

    def test_invalid_syntax_returns_message(self):
        assert validate_expression("steps.upgrade.status ==") is not None

    def test_disallowed_call_returns_message(self):
        assert validate_expression("len(vars.name)") is not None

    def test_does_not_execute_anything(self):
        # A call that would have an observable side effect if it ran must be
        # rejected by AST inspection alone, never partially evaluated first.
        msg = validate_expression("__import__('os').system('touch /tmp/should-not-exist')")
        assert msg is not None
