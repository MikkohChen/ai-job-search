"""Regression gates for the immutable, least-privilege CI contract."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED_CAR_JOBS = {
    "contracts",
    "unit",
    "adversarial",
    "evidence",
    "compile",
    "policy",
    "replay",
    "release",
}
PINNED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/dependency-review-action": "a1d282b36b6f3519aa1f3fc636f609c47dddb294",
    "oven-sh/setup-bun": "0c5077e51419868618aeaa5fe8019c62421857d6",
}
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "private key block": re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),
    "credential assignment": re.compile(
        r"""(?im)^\s*(?:password|api[_-]?key|client[_-]?secret|token)\s*[:=]\s*["']"""
        r"""(?!(?:your|example|placeholder|changeme|redacted|dummy|test|fake|sample|null|none)\b)"""
        r"""[^\s"']{8,}"""
    ),
}
SECRET_SCAN_EXCLUSIONS = {
    "tests/test_car_policy.py",
}


def parse_ci_workflow(content: str) -> dict[str, object]:
    """Parse the narrow CI surface asserted below without an external YAML dependency."""
    workflow: dict[str, object] = {"permissions": {}, "env": {}, "jobs": {}}
    jobs: dict[str, dict[str, object]] = workflow["jobs"]  # type: ignore[assignment]
    section: str | None = None
    current_job: dict[str, object] | None = None
    current_step: dict[str, object] | None = None
    for raw_line in content.splitlines():
        if not raw_line or raw_line.lstrip().startswith("#"):
            continue
        if raw_line == "permissions:":
            section = "permissions"
            continue
        if raw_line == "env:":
            section = "env"
            continue
        if raw_line == "jobs:":
            section = "jobs"
            continue
        match = re.fullmatch(r"  ([a-z][a-z0-9-]*):", raw_line)
        if section == "jobs" and match:
            current_job = {"steps": []}
            jobs[match.group(1)] = current_job
            current_step = None
            continue
        if current_job is None:
            match = re.fullmatch(r"  ([A-Za-z_]+): (.+)", raw_line)
            if match and section in {"permissions", "env"}:
                values: dict[str, str] = workflow[section]  # type: ignore[assignment]
                values[match.group(1)] = match.group(2).strip("'\"")
            continue
        if raw_line == "    permissions:":
            current_job["permissions"] = {}
            continue
        match = re.fullmatch(r"    needs: \[(.*)\]", raw_line)
        if match:
            current_job["needs"] = [value.strip() for value in match.group(1).split(",")]
            continue
        match = re.fullmatch(r"      - (uses|run): (.+)", raw_line)
        if match:
            current_step = {match.group(1): match.group(2).split(" #", 1)[0]}
            steps: list[dict[str, str]] = current_job["steps"]  # type: ignore[assignment]
            steps.append(current_step)
            continue
        match = re.fullmatch(r"        uses: (.+)", raw_line)
        if match and current_step is not None:
            current_step["uses"] = match.group(1).split(" #", 1)[0]
            continue
        if raw_line == "        with:" and current_step is not None:
            current_step["with"] = {}
            continue
        match = re.fullmatch(r'          python-version: "?([^"]+)"?', raw_line)
        if match and current_step is not None:
            with_values: dict[str, str] = current_step["with"]  # type: ignore[assignment]
            with_values["python-version"] = match.group(1)
    return workflow


def find_likely_secrets(paths: list[Path]) -> list[str]:
    """Return high-confidence secret-shaped values from readable text files."""
    findings: list[str] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path}: likely {label}")
    return findings


def tracked_text_paths() -> list[Path]:
    """Resolve tracked branch content while excluding test fixtures and this detector."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        cwd=ROOT,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    paths: list[Path] = []
    for relative in tracked:
        if not relative or relative in SECRET_SCAN_EXCLUSIONS or relative.startswith("tests/fixtures/"):
            continue
        path = ROOT / relative
        if path.is_file():
            paths.append(path)
    if WORKFLOW_PATH not in paths:
        paths.append(WORKFLOW_PATH)
    return paths


class CiPolicyTests(unittest.TestCase):
    """Catch a CI edit that weakens CAR's release or supply-chain gates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = parse_ci_workflow(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.jobs = cls.workflow["jobs"]

    def _runs(self, job_id: str) -> list[str]:
        return [
            step["run"].strip()
            for step in self.jobs[job_id]["steps"]
            if isinstance(step, dict) and "run" in step
        ]

    def _assert_run(self, job_id: str, command: str) -> None:
        self.assertIn(command, self._runs(job_id), f"{job_id} must run {command!r}")

    def test_ci_keeps_the_required_car_release_job_ids(self) -> None:
        self.assertTrue(
            REQUIRED_CAR_JOBS.issubset(self.jobs),
            f"missing required CAR jobs: {sorted(REQUIRED_CAR_JOBS - set(self.jobs))}",
        )

    def test_ci_uses_global_read_only_permissions_without_job_widening(self) -> None:
        self.assertEqual({"contents": "read"}, self.workflow.get("permissions"))
        for job_id, job in self.jobs.items():
            self.assertNotIn("permissions", job, f"{job_id} must not widen the workflow token")

    def test_every_action_reference_is_immutable_and_matches_the_reviewed_pin(self) -> None:
        action_pin = re.compile(r"^(?P<action>[^@]+)@(?P<sha>[0-9a-f]{40})$")
        seen_actions: set[str] = set()
        for job_id, job in self.jobs.items():
            for step in job.get("steps", []):
                if not isinstance(step, dict) or "uses" not in step:
                    continue
                reference = step["uses"]
                match = action_pin.fullmatch(reference)
                self.assertIsNotNone(match, f"{job_id} has a mutable action reference: {reference!r}")
                assert match is not None
                action = match.group("action")
                seen_actions.add(action)
                if action in PINNED_ACTIONS:
                    self.assertEqual(PINNED_ACTIONS[action], match.group("sha"))
        self.assertTrue(set(PINNED_ACTIONS).issubset(seen_actions))

    def test_car_jobs_use_python_312_and_the_source_import_path(self) -> None:
        self.assertEqual("src", self.workflow.get("env", {}).get("PYTHONPATH"))
        for job_id in REQUIRED_CAR_JOBS:
            setup_steps = [
                step for step in self.jobs[job_id]["steps"]
                if isinstance(step, dict) and step.get("uses", "").startswith("actions/setup-python@")
            ]
            self.assertEqual(1, len(setup_steps), f"{job_id} must set up Python exactly once")
            self.assertEqual("3.12", setup_steps[0].get("with", {}).get("python-version"))

    def test_car_jobs_run_the_exact_release_gate_commands(self) -> None:
        self._assert_run("contracts", "python3 -m unittest tests.test_car_contracts -v")
        self._assert_run(
            "contracts",
            "python3 tools/lint_contracts.py && python3 -m compileall -q src tests",
        )
        self._assert_run("contracts", "python3 -m car_job_search validate --all")
        self._assert_run("unit", "python3 -m unittest discover -s tests -t . -v")
        self._assert_run(
            "adversarial",
            "python3 -m unittest tests.test_car_intake tests.test_car_review tests.test_car_dry_run -v",
        )
        self._assert_run(
            "evidence",
            "python3 -m unittest tests.test_car_evidence tests.test_car_fit tests.test_car_application -v",
        )
        self._assert_run("compile", "python3 -m compileall -q src tests")
        self._assert_run("policy", "python3 tools/security_guards.py")
        self._assert_run("policy", "python3 -m unittest tests.test_car_policy -v")
        self._assert_run("replay", "python3 -m unittest tests.test_car_events tests.test_car_dry_run -v")
        self._assert_run("release", "python3 -m build")
        self._assert_run(
            "release",
            "python3 -m car_job_search release package --output dist/release-manifest.json",
        )

    def test_dev_dependencies_are_installed_only_for_policy_and_release_gates(self) -> None:
        install = "python -m pip install -e '.[dev]'"
        install_jobs = {job_id for job_id in self.jobs if install in self._runs(job_id)}
        self.assertEqual({"release", "lint"}, install_jobs)

    def test_release_waits_for_every_car_validation_gate(self) -> None:
        needs = self.jobs["release"].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        self.assertEqual(REQUIRED_CAR_JOBS - {"release"}, set(needs))

    def test_secret_scanner_detects_non_placeholder_credential_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "candidate.txt"
            sample.write_text('api_key = "not-a-placeholder-secret"', encoding="utf-8")
            self.assertEqual(
                [f"{sample}: likely credential assignment"],
                find_likely_secrets([sample]),
            )

    def test_tracked_branch_content_has_no_likely_committed_secrets(self) -> None:
        findings = find_likely_secrets(tracked_text_paths())
        self.assertEqual(
            [],
            findings,
            "branch content has likely credential material; remove it before release",
        )

    def test_application_builder_primitives_are_internal_to_metrics_instrumentation(self) -> None:
        import car_job_search.application as application

        primitives = {"build_application", "revise_application"}
        self.assertTrue(primitives.isdisjoint(application.__all__))
        self.assertTrue(all(not hasattr(application, name) for name in primitives))

        violations: list[str] = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if relative == "src/car_job_search/metrics/service.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "car_job_search.application.service":
                    if primitives.intersection(alias.name for alias in node.names):
                        violations.append(relative)
                if isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name) and function.id in primitives:
                        violations.append(relative)
                    if isinstance(function, ast.Attribute) and function.attr in primitives:
                        violations.append(relative)
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
