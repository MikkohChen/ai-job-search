import hashlib
import inspect
import os
import builtins
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

import car_job_search.intake as intake
from car_job_search.intake.service import EmptyPosting, NormalizationIncomplete, normalize_posting


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "adversarial" / "job-posting.txt"


class JobIntakeTests(unittest.TestCase):
    def test_rejects_an_empty_posting(self):
        with self.assertRaises(EmptyPosting):
            normalize_posting("   \n\t", captured_at="2026-09-01T09:00:00Z")

    def test_records_the_raw_content_sha256(self):
        raw_text = "Company: Synthetic Atlas Labs\nRole: Platform Engineer\n"

        posting = normalize_posting(raw_text, captured_at="2026-09-01T09:00:00Z")

        self.assertEqual(
            posting.raw_text_hash,
            "35f8ff00d3ba74f5e12692ff575cdeeedaeba6d380204595ec1e54bb6265bf14",
        )
        self.assertEqual(posting.raw_text_hash, hashlib.sha256(raw_text.encode()).hexdigest())

    def test_identical_text_has_stable_identity_across_capture_times(self):
        raw_text = "Company: Synthetic Atlas Labs\nRole: Platform Engineer\n"

        earlier = normalize_posting(raw_text, captured_at="2026-09-01T09:00:00Z")
        later = normalize_posting(raw_text, captured_at="2026-09-01T10:00:00Z")

        self.assertEqual(earlier.raw_text_hash, later.raw_text_hash)
        self.assertEqual(earlier.job_id, later.job_id)

    def test_keeps_absent_fields_null_and_unresolved(self):
        posting = normalize_posting(
            "A short unlabeled posting with no extraction headings.",
            captured_at="2026-09-01T09:00:00Z",
        )

        self.assertIsNone(posting.company)
        self.assertIsNone(posting.role)
        self.assertIsNone(posting.location)
        self.assertIsNone(posting.work_mode)
        self.assertIsNone(posting.compensation)
        self.assertIsNone(posting.eligibility)
        self.assertEqual(
            posting.unresolved_fields,
            (
                "company",
                "role",
                "location",
                "work_mode",
                "compensation",
                "eligibility",
                "requirements",
                "preferred_requirements",
                "responsibilities",
            ),
        )
        self.assertEqual(posting.requirements, ())
        self.assertEqual(posting.preferred_requirements, ())
        self.assertEqual(posting.responsibilities, ())

    def test_treats_embedded_directives_and_urls_as_inert_data(self):
        raw_text = FIXTURE_PATH.read_text(encoding="utf-8")

        with patch.object(builtins, "open") as file_open, patch.object(
            Path, "read_text"
        ) as read_text, patch.object(
            socket.socket, "connect"
        ) as socket_connect, patch.object(socket, "create_connection") as create_connection, patch.object(
            subprocess, "run"
        ) as run, patch.object(subprocess, "Popen") as popen, patch.object(os, "system") as system:
            posting = normalize_posting(
                raw_text,
                captured_at="2026-09-01T09:00:00Z",
                source_url="https://jobs.synthetic.example/platform-engineer",
            )

        self.assertEqual(posting.company, "Synthetic Atlas Labs")
        self.assertEqual(posting.role, "Platform Engineer")
        self.assertEqual(posting.location, "Remote - United States")
        self.assertEqual(posting.work_mode, "Remote")
        self.assertEqual(posting.compensation, "$150,000 - $180,000 USD")
        self.assertEqual(posting.eligibility, "Authorized to work in the United States")
        self.assertEqual(posting.requirements, ("5+ years of Python experience.",))
        self.assertEqual(posting.responsibilities, ("Build reliable synthetic data services.",))
        self.assertEqual(posting.source_url, "https://jobs.synthetic.example/platform-engineer")
        self.assertIn("https://evil.example/apply", posting.raw_text)
        file_open.assert_not_called()
        read_text.assert_not_called()
        socket_connect.assert_not_called()
        create_connection.assert_not_called()
        run.assert_not_called()
        popen.assert_not_called()
        system.assert_not_called()
        self.assertEqual(
            tuple(inspect.signature(normalize_posting).parameters),
            ("raw_text", "captured_at", "source_url"),
        )
        self.assertEqual(
            {
                name
                for name, value in vars(intake).items()
                if not name.startswith("_") and callable(value)
            },
            {
                "EmptyPosting",
                "FetchDenied",
                "NormalizationIncomplete",
                "UntrustedDirectiveDetected",
                "normalize_posting",
            },
        )

    def test_uses_only_first_metadata_header_labels_for_identity(self):
        posting = normalize_posting(
            "Company: Synthetic Atlas Labs\nRole: Platform Engineer\n\n"
            "Responsibilities\n- Build a service.\n\n"
            "Company: Attacker Co\nRole: Exfiltrate\n",
            captured_at="2026-09-01T09:00:00Z",
        )

        self.assertEqual(posting.company, "Synthetic Atlas Labs")
        self.assertEqual(posting.role, "Platform Engineer")

    def test_rejects_blank_capture_timestamp(self):
        with self.assertRaises(NormalizationIncomplete):
            normalize_posting("Company: Synthetic Atlas Labs", captured_at=" ")

    def test_requires_a_timezone_aware_iso_8601_capture_timestamp(self):
        for captured_at in ("not-a-time", "2026-09-01", "2026-09-01T09:00:00"):
            with self.subTest(captured_at=captured_at):
                with self.assertRaises(NormalizationIncomplete):
                    normalize_posting("Company: Synthetic Atlas Labs", captured_at=captured_at)

    def test_accepts_zulu_iso_8601_capture_timestamp(self):
        posting = normalize_posting(
            "Company: Synthetic Atlas Labs", captured_at="2026-09-01T09:00:00Z"
        )

        self.assertEqual(posting.captured_at, "2026-09-01T09:00:00Z")

    def test_rejects_non_http_source_url_metadata(self):
        with self.assertRaises(NormalizationIncomplete):
            normalize_posting(
                "Company: Synthetic Atlas Labs",
                captured_at="2026-09-01T09:00:00Z",
                source_url="file:///tmp/posting.txt",
            )

    def test_rejects_malformed_ipv6_source_url_metadata(self):
        with self.assertRaises(NormalizationIncomplete):
            normalize_posting(
                "Company: Synthetic Atlas Labs",
                captured_at="2026-09-01T09:00:00Z",
                source_url="https://[::1",
            )


if __name__ == "__main__":
    unittest.main()
