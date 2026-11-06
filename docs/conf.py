# SPDX-License-Identifier: MIT
"""Operator handbook, adapted from the MIT-licensed WsprryPi-Docs scaffold."""

import os
from pathlib import Path
import re
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE / "_ext"))

project = "RP1-GPIO-CLK-DKMS"
author = "Lee C. Bussy"
copyright = "2026, Lee Bussy; scaffold copyright 2024 Lee Bussy"


def _git(*arguments):
    try:
        return subprocess.check_output(
            ["git", *arguments], cwd=SOURCE, stderr=subprocess.DEVNULL,
            text=True, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


branch = _git("branch", "--show-current")
revision = (os.environ.get("READTHEDOCS_GIT_COMMIT_HASH", "").strip()
            or _git("rev-parse", "HEAD"))
short_revision = revision[:7] if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision) else ""
version = (os.environ.get("READTHEDOCS_VERSION_NAME", "").strip()
           or os.environ.get("READTHEDOCS_VERSION", "").strip()
           or branch or "local")
version = "main" if version == "latest" else version
release = f"{version}-{short_revision}" if short_revision else version
source_ref = (os.environ.get("READTHEDOCS_GIT_IDENTIFIER", "").strip()
              or branch or revision or "HEAD")
if os.environ.get("READTHEDOCS_VERSION_TYPE") == "external" and short_revision:
    source_ref = revision

extensions = ["image_delivery", "myst_parser"]
source_suffix = {".md": "markdown"}
root_doc = "index"
language = "en"
exclude_patterns = ["_build", ".venv", "Thumbs.db", ".DS_Store"]
myst_enable_extensions = ["colon_fence", "deflist", "tasklist"]
myst_heading_anchors = 3
nitpicky = True
pygments_style = None

html_theme = "sphinx_rtd_theme"
html_title = "RP1-GPIO-CLK-DKMS operator handbook"
html_theme_options = {
    "logo_only": False,
    "prev_next_buttons_location": "both",
    "style_external_links": True,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 3,
    "includehidden": True,
    "titles_only": True,
}
templates_path = ["_templates"]
html_static_path = ["_static"]
html_logo = "_static/WsprryPi_Logo.png"
html_favicon = "_static/favicon.ico"
html_css_files = ["css/custom.css"]
html_js_files = ["js/accessibility.js"]
html_context = {
    "display_github": True,
    "github_user": "WsprryPi",
    "github_repo": "RP1-GPIO-CLK-DKMS",
    "github_version": source_ref,
    "conf_py_path": "/docs/",
}

htmlhelp_basename = "RP1DKMSdoc"
latex_documents = [
    ("index", "RP1-GPIO-CLK-DKMS.tex", "RP1-GPIO-CLK-DKMS Operator Handbook",
     author, "manual"),
]
man_pages = [
    ("index", "rp1-gpclk-dkms", "RP1-GPIO-CLK-DKMS Operator Handbook", [author], 7),
]
texinfo_documents = [
    ("index", "RP1-GPIO-CLK-DKMS", "RP1-GPIO-CLK-DKMS Operator Handbook", author,
     "RP1-GPIO-CLK-DKMS", "WsprryPi-managed RP1 clock output and route administration.",
     "System administration"),
]
epub_title = html_title
epub_exclude_files = ["search.html", "_static/LICENSE-WsprryPi-Docs.txt"]

# Local static assets used by the HTML theme are not EPUB reading content.
suppress_warnings = ["epub.unknown_project_files"]
