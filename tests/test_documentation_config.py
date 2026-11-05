# SPDX-License-Identifier: MIT
"""Exercise documentation identity in local, detached and hosted checkouts."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch


DOCS = Path(__file__).resolve().parents[1] / "docs"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
HOSTED_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"


class DocumentationIdentityTests(unittest.TestCase):
    def configure(self, environment=None, branch="devel", missing_git=False):
        def git(command, **options):
            self.assertEqual(options["cwd"], DOCS)
            self.assertEqual(options["timeout"], 5)
            if missing_git:
                raise FileNotFoundError("git unavailable in exported source")
            return {("git", "branch", "--show-current"): branch + "\n",
                    ("git", "rev-parse", "HEAD"): COMMIT + "\n"}[tuple(command)]

        with patch.dict(os.environ, environment or {}, clear=True), \
                patch("subprocess.check_output", side_effect=git), \
                patch.object(sys, "path", list(sys.path)):
            configuration = runpy.run_path(str(DOCS / "conf.py"))
            configuration["extension_path"] = sys.path[0]
            return configuration

    def test_local_branch_uses_actual_commit(self):
        configuration = self.configure()
        self.assertEqual(configuration["version"], "devel")
        self.assertEqual(configuration["release"], "devel-0123456")
        self.assertEqual(configuration["html_context"]["github_version"], "devel")

    def test_hosted_names_and_latest_alias(self):
        for name, expected in (("latest", "main"), ("main", "main"), ("devel", "devel")):
            with self.subTest(name=name):
                configuration = self.configure({
                    "READTHEDOCS_VERSION_NAME": name,
                    "READTHEDOCS_GIT_IDENTIFIER": expected,
                    "READTHEDOCS_GIT_COMMIT_HASH": HOSTED_COMMIT,
                }, branch="")
                self.assertEqual(configuration["version"], expected)
                self.assertEqual(configuration["release"], expected + "-fedcba9")
                self.assertEqual(configuration["html_context"]["github_version"], expected)

    def test_slug_fallback_when_verbose_name_is_absent(self):
        configuration = self.configure({"READTHEDOCS_VERSION": "latest"}, branch="")
        self.assertEqual(configuration["version"], "main")
        self.assertEqual(configuration["release"], "main-0123456")

    def test_pull_request_source_link_is_the_checked_out_commit(self):
        configuration = self.configure({
            "READTHEDOCS_VERSION": "14", "READTHEDOCS_VERSION_TYPE": "external",
            "READTHEDOCS_GIT_IDENTIFIER": "14", "READTHEDOCS_GIT_COMMIT_HASH": HOSTED_COMMIT,
        }, branch="")
        self.assertEqual(configuration["release"], "14-fedcba9")
        self.assertEqual(configuration["html_context"]["github_version"], HOSTED_COMMIT)

    def test_detached_checkout_has_a_usable_source_link(self):
        configuration = self.configure(branch="")
        self.assertEqual(configuration["version"], "local")
        self.assertEqual(configuration["release"], "local-0123456")
        self.assertEqual(configuration["html_context"]["github_version"], COMMIT)

    def test_exported_source_does_not_invent_a_commit(self):
        configuration = self.configure(branch="", missing_git=True)
        self.assertEqual(configuration["release"], "local")
        self.assertEqual(configuration["html_context"]["github_version"], "HEAD")

    def test_extension_path_is_independent_of_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                configuration = self.configure()
                self.assertEqual(configuration["extension_path"], str(DOCS / "_ext"))
            finally:
                # Windows cannot remove a directory while it is the process cwd.
                os.chdir(previous)


if __name__ == "__main__":
    __import__("nonempty_unittest").main()
