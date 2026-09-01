"""Boundary tests for the repository validation and release CLI."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


SCHEMA_NAMES = (
    "application-package.schema.json",
    "approval-record.schema.json",
    "evidence-claim.schema.json",
    "fit-assessment.schema.json",
    "interview-pack.schema.json",
    "job-posting.schema.json",
    "outcome-event.schema.json",
    "release-manifest.schema.json",
    "review-finding.schema.json",
    "runtime-projection.schema.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseFixture:
    """A clean minimal Git repository containing the release inputs."""

    def __init__(self, directory: Path) -> None:
        self.root = directory
        self.root.mkdir(exist_ok=True)
        (self.root / "docs").mkdir()
        (self.root / "schemas").mkdir()
        (self.root / "dist").mkdir()
        (self.root / "src").mkdir()
        (self.root / "tools").mkdir()
        (self.root / ".gitignore").write_text("dist/\n__pycache__/\n", encoding="utf-8")
        shutil.copytree(
            ROOT / "src" / "car_job_search",
            self.root / "src" / "car_job_search",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for name in (
            "strategy-car-ai-job-search-integration.md",
            "execution-pack-car-ai-job-search-integration.md",
            "CLAUDE.md",
            "SPEC.md",
        ):
            shutil.copyfile(ROOT / name, self.root / name)
        shutil.copyfile(ROOT / "docs" / "RUNBOOK.md", self.root / "docs" / "RUNBOOK.md")
        shutil.copyfile(ROOT / "tools" / "lint_contracts.py", self.root / "tools" / "lint_contracts.py")
        for name in SCHEMA_NAMES:
            shutil.copyfile(ROOT / "schemas" / name, self.root / "schemas" / name)
        (self.root / "docs" / "source-manifest.md").write_text(
            "\n".join(
                (
                    "| Source | Version / identity | SHA-256 / commit | Authority | State |",
                    "|---|---|---|---|---|",
                    "| Strategy | `1.0.0` | "
                    f"`{_sha256(self.root / 'strategy-car-ai-job-search-integration.md')}` | Product | [K] |",
                    "| Execution pack | `1.0.0` | "
                    f"`{_sha256(self.root / 'execution-pack-car-ai-job-search-integration.md')}` | Runtime | [K] |",
                    "",
                )
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "tests@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "CAR test"], check=True
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True
        )


class CarCliTests(unittest.TestCase):
    """The CLI validates inert repository metadata and writes one artifact."""

    def test_validate_all_command_accepts_current_repository_contracts(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")

        result = subprocess.run(
            [sys.executable, "-m", "car_job_search", "validate", "--all"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "validation: OK\n")
        self.assertEqual(result.stderr, "")

    def test_release_package_writes_deterministic_manifest_to_explicit_path(self) -> None:
        from car_job_search.release.service import package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            first = fixture.root / "dist" / "first.json"
            second = fixture.root / "dist" / "second.json"

            package_release(first, repository_root=fixture.root)
            package_release(second, repository_root=fixture.root)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            manifest = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "1.0.0")
            self.assertRegex(manifest["commit_sha"], r"^[0-9a-f]{40}$")
            self.assertEqual(manifest["projection_contract_version"], "1.0.0")
            self.assertEqual(manifest["test_summary"]["status"], "unverified")
            self.assertEqual(
                manifest["source_checksums"]["strategy-car-ai-job-search-integration.md"],
                _sha256(fixture.root / "strategy-car-ai-job-search-integration.md"),
            )
            self.assertNotIn("generated_at", manifest)

    def test_release_package_resolves_relative_output_from_repository_root(self) -> None:
        from car_job_search.release.service import package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))

            package_release(Path("dist/relative.json"), repository_root=fixture.root)

            self.assertTrue((fixture.root / "dist" / "relative.json").is_file())

    def test_release_command_resolves_relative_output_from_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = ReleaseFixture(base / "repository")
            caller = base / "caller"
            caller.mkdir()
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(fixture.root / "src")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "car_job_search",
                    "release",
                    "package",
                    "--output",
                    "dist/from-cli.json",
                ],
                cwd=caller,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((fixture.root / "dist" / "from-cli.json").is_file())
            self.assertFalse((caller / "dist" / "from-cli.json").exists())

    def test_release_package_rejects_a_dangling_symlink_destination(self) -> None:
        from car_job_search.release.service import ReleaseOutputError, package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            destination = fixture.root / "dist" / "manifest.json"
            os.symlink("missing-target.json", destination)

            with self.assertRaisesRegex(ReleaseOutputError, "output path already exists"):
                package_release(destination, repository_root=fixture.root)

            self.assertTrue(destination.is_symlink())

    def test_release_package_cleans_up_when_atomic_publish_fails(self) -> None:
        from car_job_search.release.service import ReleaseOutputError, package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            destination = fixture.root / "dist" / "manifest.json"

            with mock.patch("car_job_search.release.service.os.link", side_effect=OSError("denied")):
                with self.assertRaisesRegex(ReleaseOutputError, "could not write output"):
                    package_release(destination, repository_root=fixture.root)

            self.assertFalse(os.path.lexists(destination))
            self.assertEqual(list((fixture.root / "dist").iterdir()), [])

    def test_release_package_rejects_dirty_repository(self) -> None:
        from car_job_search.release.service import ReleaseDirtyTree, package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            (fixture.root / "untracked.txt").write_text("not released\n", encoding="utf-8")

            with self.assertRaisesRegex(ReleaseDirtyTree, "repository has uncommitted changes"):
                package_release(fixture.root / "dist" / "manifest.json", repository_root=fixture.root)

    def test_release_command_reports_dirty_tree_without_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "release-manifest.json"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(ROOT / "src")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "car_job_search",
                    "release",
                    "package",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "release package failed: repository has uncommitted changes\n")
            self.assertFalse(output.exists())

    def test_release_package_requires_existing_output_parent(self) -> None:
        from car_job_search.release.service import ReleaseOutputError, package_release

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            output = fixture.root / "missing" / "manifest.json"

            with self.assertRaisesRegex(ReleaseOutputError, "output parent does not exist"):
                package_release(output, repository_root=fixture.root)

    def test_validation_requires_the_contract_linter(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            (fixture.root / "tools" / "lint_contracts.py").unlink()

            failures = validate_repository(fixture.root)

            self.assertIn("tools/lint_contracts.py: required contract linter is missing", failures)

    def test_validation_requires_the_source_manifest(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            (fixture.root / "docs" / "source-manifest.md").unlink()

            failures = validate_repository(fixture.root)

            self.assertIn("docs/source-manifest.md: required source manifest is missing", failures)

    def test_validation_requires_every_canonical_schema(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            (fixture.root / "schemas" / "release-manifest.schema.json").unlink()

            failures = validate_repository(fixture.root)

            self.assertIn(
                "schemas: missing canonical schema documents: release-manifest.schema.json",
                failures,
            )

    def test_validation_checks_extractions_at_the_supplied_root(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            claude = fixture.root / "CLAUDE.md"
            claude.write_text(claude.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn("CLAUDE.md: differs from execution-pack extraction", failures)

    def test_validation_rejects_unknown_schema_files(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            (fixture.root / "schemas" / "unknown.schema.json").write_text("{}", encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn("schemas: unknown schema documents: unknown.schema.json", failures)

    def test_validation_rejects_duplicate_schema_ids(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            source = fixture.root / "schemas" / "approval-record.schema.json"
            value = json.loads(source.read_text(encoding="utf-8"))
            value["$id"] = "urn:car:application-package:1.0.0"
            source.write_text(json.dumps(value), encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn("schemas: duplicate $id: urn:car:application-package:1.0.0", failures)

    def test_validation_rejects_invalid_schema_vocabulary(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            source = fixture.root / "schemas" / "approval-record.schema.json"
            value = json.loads(source.read_text(encoding="utf-8"))
            value["type"] = "not-a-json-schema-type"
            source.write_text(json.dumps(value), encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn(
                "schemas/approval-record.schema.json: type must be a JSON Schema type",
                failures,
            )

    def test_validation_rejects_a_missing_current_document_pointer(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            source = fixture.root / "schemas" / "approval-record.schema.json"
            value = json.loads(source.read_text(encoding="utf-8"))
            value["properties"]["alias"] = {"$ref": "#/properties/missing"}
            source.write_text(json.dumps(value), encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn(
                "schemas/approval-record.schema.json/properties/alias: unresolved local reference: #/properties/missing",
                failures,
            )

    def test_validation_rejects_a_missing_cross_document_pointer(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            source = fixture.root / "schemas" / "approval-record.schema.json"
            value = json.loads(source.read_text(encoding="utf-8"))
            value["properties"]["alias"] = {
                "$ref": "application-package.schema.json#/properties/missing"
            }
            source.write_text(json.dumps(value), encoding="utf-8")

            failures = validate_repository(fixture.root)

            self.assertIn(
                "schemas/approval-record.schema.json/properties/alias: unresolved local reference: "
                "application-package.schema.json#/properties/missing",
                failures,
            )

    def test_validation_accepts_valid_current_and_escaped_cross_document_pointers(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            application = fixture.root / "schemas" / "application-package.schema.json"
            application_value = json.loads(application.read_text(encoding="utf-8"))
            application_value["properties"]["a/b~c"] = {"type": "string"}
            application.write_text(json.dumps(application_value), encoding="utf-8")
            approval = fixture.root / "schemas" / "approval-record.schema.json"
            approval_value = json.loads(approval.read_text(encoding="utf-8"))
            approval_value["properties"]["current_alias"] = {"$ref": "#/properties/action"}
            approval_value["properties"]["remote_alias"] = {
                "$ref": "application-package.schema.json#/properties/a~1b~0c"
            }
            approval.write_text(json.dumps(approval_value), encoding="utf-8")

            self.assertEqual(validate_repository(fixture.root), [])

    def test_validation_rejects_external_action_public_api_but_allows_bookkeeping(self) -> None:
        from car_job_search.release.service import validate_repository

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(Path(directory))
            unsafe = fixture.root / "src" / "car_job_search" / "unsafe.py"
            unsafe.write_text(
                "def sync_car():\n    pass\n\ndef apply_now():\n    pass\n\ndef send_now():\n    pass\n"
                "\ndef submit_now():\n    pass\n\ndef dispatch_now():\n    pass\n\ndef deliver_now():\n    pass\n"
                "\ndef record_delivery():\n    pass\n",
                encoding="utf-8",
            )

            failures = validate_repository(fixture.root)

            self.assertIn(
                "src/car_job_search/unsafe.py: prohibited public authority API: sync_car",
                failures,
            )
            self.assertIn(
                "src/car_job_search/unsafe.py: prohibited public authority API: apply_now",
                failures,
            )
            for name in ("send_now", "submit_now", "dispatch_now", "deliver_now"):
                self.assertIn(
                    f"src/car_job_search/unsafe.py: prohibited public authority API: {name}",
                    failures,
                )
            self.assertNotIn(
                "src/car_job_search/unsafe.py: prohibited public authority API: record_delivery",
                failures,
            )


if __name__ == "__main__":
    unittest.main()
