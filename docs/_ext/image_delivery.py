# SPDX-License-Identifier: MIT
# Adapted from WsprryPi-Docs; copyright 2024 Lee Bussy.
"""Add initial-HTML image loading and layout hints to documentation pages."""

from __future__ import annotations

from urllib.parse import urlparse

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.util.images import get_image_size
from sphinx.writers.html5 import HTML5Translator


class ImageDeliveryHTMLTranslator(HTML5Translator):
    """Emit asynchronous decoding hints for rendered raster images."""

    def visit_image(self, node: nodes.image) -> None:
        body_start = len(self.body)
        super().visit_image(node)

        for index in range(body_start, len(self.body)):
            if "<img " in self.body[index]:
                # Docutils emits lazy loading itself, but omits an explicit
                # eager hint. Avoid duplicate attributes across writer versions.
                fragment = self.body[index]
                hints = []
                if ' decoding="' not in fragment:
                    hints.append('decoding="async"')
                if node.get("loading") == "eager" and ' loading="' not in fragment:
                    hints.append('loading="eager"')
                if hints:
                    self.body[index] = fragment.replace(
                        "<img ", f'<img {" ".join(hints)} ', 1
                    )
                break


def configure_image_delivery(
    app: Sphinx, doctree: nodes.document, docname: str
) -> None:
    """Keep the first local content image eager and defer later images.

    The first content image may be visible in the initial viewport. Keeping it
    eager avoids delaying explanatory content without requiring page-specific
    exceptions. Later content images default to lazy loading; explicit author
    choices take precedence. The navigation logo is emitted by the theme
    template and is intentionally outside this transform.
    """

    # Loading hints and pixel dimensions belong to HTML, not shared print
    # doctrees (where an unsized image should retain the writer's defaults).
    if app.builder.format != "html":
        return

    first_local_image = True

    for image in doctree.findall(nodes.image):
        uri = image.get("uri", "")
        parsed = urlparse(uri)
        if parsed.scheme or parsed.netloc:
            continue

        image.setdefault("loading", "eager" if first_local_image else "lazy")
        first_local_image = False

        # A single authored width/height can use pixels, percentages or physical
        # units. Filling both from the file would erase that sizing instruction.
        # Leave explicit sizing and scale interactions to the Sphinx writer.
        if "width" in image or "height" in image:
            continue

        size = get_image_size(app.srcdir / uri)
        if size is None:
            continue

        image["width"] = str(size[0])
        image["height"] = str(size[1])


def setup(app: Sphinx) -> dict[str, object]:
    app.connect("doctree-resolved", configure_image_delivery)
    app.set_translator("html", ImageDeliveryHTMLTranslator, override=True)
    return {
        "version": "2",
        # Rebuild pages cached before the sizing/loading policy was corrected.
        "env_version": 1,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
