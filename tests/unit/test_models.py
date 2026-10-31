"""Tests for the shared data models.

All secret-looking values in this file are fake.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from deploy_agent.models import (
    Action,
    Confidence,
    DeploymentPlan,
    Diagnosis,
    PreflightResult,
    ProjectInfo,
    SafetyTier,
    Severity,
)

FAKE_SECRET = "s3cr3t-hunter2-not-real"


def project_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "language": "python",
        "framework": "django",
        "runtime_version": "3.12",
        "ports": (8000,),
        "env_var_names": ("DATABASE_URL", "SECRET_KEY"),
        "migration_tool": "alembic",
        "detected_files": ("pyproject.toml", "src/app/main.py"),
    }
    return values | overrides


def failed_check_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "check_name": "python-version",
        "passed": False,
        "severity": Severity.ERROR,
        "evidence": "Found Python 3.9, project needs 3.12",
        "suggested_fix": "Install Python 3.12",
    }
    return values | overrides


def action_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "what": "Add a health check route",
        "tier": SafetyTier.NEEDS_APPROVAL,
        "reversible": True,
        "undo_instructions": "Revert the commit",
    }
    return values | overrides


def diagnosis_kwargs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "cause": "The app listens on the wrong port",
        "evidence_line": "Error: bind EADDRINUSE 0.0.0.0:8000",
        "confidence": Confidence.MEDIUM,
        "alternative_causes": ("Another process already uses the port",),
        "suggested_next_step": "Read the port setting in the provider config",
        "next_step_tier": SafetyTier.AUTO,
    }
    return values | overrides


class TestStrictRulesApplyToEveryModel:
    @pytest.mark.parametrize(
        ("model", "kwargs"),
        [
            (ProjectInfo, project_kwargs()),
            (PreflightResult, failed_check_kwargs()),
            (Action, action_kwargs()),
            (DeploymentPlan, {"steps": (Action(**action_kwargs()),)}),
            (Diagnosis, diagnosis_kwargs()),
        ],
    )
    def test_unknown_field_is_rejected(self, model: Any, kwargs: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            model(**kwargs, password=FAKE_SECRET)

    def test_model_cannot_be_changed_after_creation(self) -> None:
        action = Action(**action_kwargs(tier=SafetyTier.FORBIDDEN))

        with pytest.raises(ValidationError):
            action.tier = SafetyTier.AUTO

    def test_rejected_value_does_not_appear_in_error_message(self) -> None:
        bad_name = f"DATABASE_URL=postgres://admin:{FAKE_SECRET}@db/app"

        with pytest.raises(ValidationError) as caught:
            ProjectInfo(**project_kwargs(env_var_names=(bad_name,)))

        assert FAKE_SECRET not in str(caught.value)

    def test_unknown_field_value_does_not_appear_in_error_message(self) -> None:
        with pytest.raises(ValidationError) as caught:
            ProjectInfo(**project_kwargs(), api_key=FAKE_SECRET)

        assert FAKE_SECRET not in str(caught.value)


class TestProjectInfo:
    def test_only_approved_fields_exist(self) -> None:
        """Adding a field must be a reviewed decision: it could become a path for secrets."""
        assert set(ProjectInfo.model_fields) == {
            "language",
            "framework",
            "runtime_version",
            "ports",
            "env_var_names",
            "migration_tool",
            "detected_files",
        }

    def test_valid_project_is_accepted(self) -> None:
        project = ProjectInfo(**project_kwargs())

        assert project.env_var_names == ("DATABASE_URL", "SECRET_KEY")
        assert project.ports == (8000,)

    def test_optional_details_can_be_left_out(self) -> None:
        project = ProjectInfo(language="node")

        assert project.framework is None
        assert project.runtime_version is None
        assert project.migration_tool is None
        assert project.ports == ()
        assert project.env_var_names == ()
        assert project.detected_files == ()

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "DATABASE_URL=postgres://localhost/app",
            "API KEY",
            "1STARTS_WITH_DIGIT",
            "HAS-DASH",
            "TRAILING_NEWLINE\n",
            "A" * 129,
        ],
    )
    def test_bad_env_var_name_is_rejected(self, name: str) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(env_var_names=(name,)))

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_port_out_of_range_is_rejected(self, port: int) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(ports=(port,)))

    @pytest.mark.parametrize("port", [1, 65535])
    def test_port_range_limits_are_accepted(self, port: int) -> None:
        assert ProjectInfo(**project_kwargs(ports=(port,))).ports == (port,)

    @pytest.mark.parametrize("port", ["8000", 8000.0, True])
    def test_port_of_wrong_type_is_rejected(self, port: object) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(ports=(port,)))

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/etc/passwd",
            "\\server\\share\\file",
            "C:\\Users\\me\\.env",
            "../outside.txt",
            "src/../../outside.txt",
            "src\\..\\..\\outside.txt",
            "config/DB=postgres://u:p@host",
            "file\nname.txt",
            "a" * 261,
        ],
    )
    def test_bad_detected_file_path_is_rejected(self, path: str) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(detected_files=(path,)))

    @pytest.mark.parametrize(
        "path",
        [
            "pyproject.toml",
            "src/app/main.py",
            "src\\app\\main.py",
            ".github/workflows/deploy.yml",
            "app/(group)/page.tsx",
            "my file..backup.txt",
        ],
    )
    def test_normal_detected_file_path_is_accepted(self, path: str) -> None:
        assert ProjectInfo(**project_kwargs(detected_files=(path,))).detected_files == (path,)

    @pytest.mark.parametrize("field", ["language", "framework", "migration_tool"])
    @pytest.mark.parametrize(
        "value",
        ["", "has space", "key=value", "postgres://u:p@host/db", "x" * 65, "-leading-dash"],
    )
    def test_label_field_rejects_non_label_text(self, field: str, value: str) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(**{field: value}))

    @pytest.mark.parametrize("label", ["python", "next.js", "c++", "prisma-migrate", "Django_5"])
    def test_label_field_accepts_real_names(self, label: str) -> None:
        assert ProjectInfo(**project_kwargs(framework=label)).framework == label

    @pytest.mark.parametrize(
        "version", ["3.12", "3.12.1", "20", ">=3.12", ">=3.12,<4", "^20.1", "~=3.12"]
    )
    def test_runtime_version_accepts_real_versions(self, version: str) -> None:
        assert ProjectInfo(**project_kwargs(runtime_version=version)).runtime_version == version

    @pytest.mark.parametrize(
        "version",
        ["", "latest", "3.12 or so", "a1b2c3", "1" + "0" * 32, "PASSWORD=hunter2"],
    )
    def test_runtime_version_rejects_non_version_text(self, version: str) -> None:
        with pytest.raises(ValidationError):
            ProjectInfo(**project_kwargs(runtime_version=version))


class TestPreflightResult:
    def test_failed_check_with_evidence_and_fix_is_accepted(self) -> None:
        result = PreflightResult(**failed_check_kwargs())

        assert result.passed is False
        assert result.severity is Severity.ERROR

    def test_passed_check_needs_no_evidence_or_fix(self) -> None:
        result = PreflightResult(
            check_name="python-version",
            passed=True,
            severity=Severity.INFO,
        )

        assert result.evidence is None
        assert result.suggested_fix is None

    @pytest.mark.parametrize("field", ["evidence", "suggested_fix"])
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_failed_check_needs_evidence_and_fix(self, field: str, value: str | None) -> None:
        with pytest.raises(ValidationError):
            PreflightResult(**failed_check_kwargs(**{field: value}))

    @pytest.mark.parametrize("passed", ["yes", "true", 1])
    def test_passed_must_be_a_real_boolean(self, passed: object) -> None:
        with pytest.raises(ValidationError):
            PreflightResult(**failed_check_kwargs(passed=passed))

    def test_unknown_severity_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PreflightResult(**failed_check_kwargs(severity="catastrophic"))


class TestAction:
    def test_reversible_action_with_undo_is_accepted(self) -> None:
        assert Action(**action_kwargs()).undo_instructions == "Revert the commit"

    def test_irreversible_action_without_undo_is_accepted(self) -> None:
        action = Action(**action_kwargs(reversible=False, undo_instructions=None))

        assert action.undo_instructions is None

    @pytest.mark.parametrize("undo", [None, "", "   "])
    def test_reversible_action_needs_undo_instructions(self, undo: str | None) -> None:
        with pytest.raises(ValidationError):
            Action(**action_kwargs(undo_instructions=undo))

    def test_irreversible_action_cannot_claim_undo_instructions(self) -> None:
        with pytest.raises(ValidationError):
            Action(**action_kwargs(reversible=False, undo_instructions="Restore a backup"))

    def test_blank_description_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Action(**action_kwargs(what="   "))

    @pytest.mark.parametrize("tier", ["auto", "needs_approval", "manual", "forbidden"])
    def test_tiers_have_the_agreed_names(self, tier: str) -> None:
        action = Action.model_validate_json(
            f'{{"what": "Do it", "tier": "{tier}", "reversible": false}}'
        )

        assert action.tier == tier

    def test_unknown_tier_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Action(**action_kwargs(tier="whenever"))


class TestDeploymentPlan:
    def test_steps_keep_their_order(self) -> None:
        first = Action(**action_kwargs(what="Build the image"))
        second = Action(**action_kwargs(what="Run migrations"))
        third = Action(**action_kwargs(what="Promote to production"))

        plan = DeploymentPlan(steps=(first, second, third))

        assert [step.what for step in plan.steps] == [
            "Build the image",
            "Run migrations",
            "Promote to production",
        ]

    def test_plan_with_no_steps_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DeploymentPlan(steps=())

    def test_invalid_step_in_json_is_rejected(self) -> None:
        reversible_without_undo = '{"what": "Do it", "tier": "auto", "reversible": true}'

        with pytest.raises(ValidationError):
            DeploymentPlan.model_validate_json(f'{{"steps": [{reversible_without_undo}]}}')

    def test_forbidden_step_is_kept_for_the_policy_engine_to_see(self) -> None:
        step = Action(
            **action_kwargs(tier=SafetyTier.FORBIDDEN, reversible=False, undo_instructions=None)
        )

        assert DeploymentPlan(steps=(step,)).steps[0].tier is SafetyTier.FORBIDDEN


class TestDiagnosis:
    def test_valid_diagnosis_is_accepted(self) -> None:
        diagnosis = Diagnosis(**diagnosis_kwargs())

        assert diagnosis.confidence is Confidence.MEDIUM
        assert diagnosis.next_step_tier is SafetyTier.AUTO

    def test_diagnosis_with_no_alternative_cause_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Diagnosis(**diagnosis_kwargs(alternative_causes=()))

    def test_diagnosis_missing_alternative_causes_is_rejected(self) -> None:
        kwargs = diagnosis_kwargs()
        del kwargs["alternative_causes"]

        with pytest.raises(ValidationError):
            Diagnosis(**kwargs)

    @pytest.mark.parametrize(
        "alternative",
        ["The app listens on the wrong port", "  the app listens on THE WRONG PORT  "],
    )
    def test_alternative_cannot_repeat_the_main_cause(self, alternative: str) -> None:
        with pytest.raises(ValidationError):
            Diagnosis(**diagnosis_kwargs(alternative_causes=(alternative,)))

    def test_blank_alternative_cause_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Diagnosis(**diagnosis_kwargs(alternative_causes=("   ",)))

    @pytest.mark.parametrize("field", ["cause", "evidence_line", "suggested_next_step"])
    def test_blank_required_text_is_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            Diagnosis(**diagnosis_kwargs(**{field: "   "}))

    def test_unknown_confidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Diagnosis(**diagnosis_kwargs(confidence="certain"))

    def test_diagnosis_can_be_read_from_json(self) -> None:
        """AI output arrives as JSON, so strict rules must still accept valid JSON."""
        diagnosis = Diagnosis.model_validate_json(
            """
            {
              "cause": "Missing dependency",
              "evidence_line": "ModuleNotFoundError: No module named 'flask'",
              "confidence": "high",
              "alternative_causes": ["Wrong virtual environment"],
              "suggested_next_step": "Check requirements.txt",
              "next_step_tier": "needs_approval"
            }
            """
        )

        assert diagnosis.confidence is Confidence.HIGH
        assert diagnosis.alternative_causes == ("Wrong virtual environment",)
        assert diagnosis.next_step_tier is SafetyTier.NEEDS_APPROVAL
