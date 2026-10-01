#!/usr/bin/env python3
# Copyright (C) 2026 David Brum
# SPDX-License-Identifier: GPL-2.0-or-later
"""Recursively find and relink missing image files in an Inkscape document all at once."""

import base64
import mimetypes
import os
import sys
import urllib.parse
import urllib.request

import inkex
from inkex.localization import inkex_gettext as _


class FixMissingImages(inkex.EffectExtension):
    """Extension to scan SVG for missing linked images and relink them recursively."""

    def add_arguments(self, pars):
        pars.add_argument(
            "--search_dir",
            type=str,
            default="",
            help="Directory to search recursively for missing image files",
        )
        pars.add_argument(
            "--search_doc_dir",
            type=inkex.Boolean,
            default=True,
            help="Also search the SVG document folder recursively",
        )
        pars.add_argument(
            "--path_style",
            type=str,
            default="relative",
            help="Relinked path style: 'relative' or 'absolute'",
        )
        pars.add_argument(
            "--case_insensitive",
            type=inkex.Boolean,
            default=True,
            help="Case-insensitive filename matching",
        )
        pars.add_argument(
            "--embed_found",
            type=inkex.Boolean,
            default=False,
            help="Embed found images as Base64 data inside the SVG",
        )
        pars.add_argument(
            "--relink_all",
            type=inkex.Boolean,
            default=False,
            help="Relink all images even if already pointing to an existing file",
        )
        pars.add_argument(
            "--dry_run",
            type=inkex.Boolean,
            default=False,
            help="Simulate the search and report results without modifying SVG",
        )
        pars.add_argument(
            "--selected_only",
            type=inkex.Boolean,
            default=False,
            help="Process only selected image objects",
        )

    def effect(self):
        if self.options.selected_only:
            images = [
                node for node in self.svg.selection
                if node is not self.svg and node.tag.endswith("image")
            ]
            if not images:
                raise inkex.AbortExtension(
                    _("No <image> objects are currently selected. "
                      "Select one or more images, or disable 'Process only selected image objects'.")
                )
        else:
            images = self.svg.xpath("//svg:image")
            if not images:
                raise inkex.AbortExtension(_("No <image> elements found in this document."))

        doc_dir = self._get_document_dir()
        search_roots = self._get_search_roots(doc_dir)
        if not search_roots:
            raise inkex.AbortExtension(
                _("No valid search directory found.\n"
                  "Please choose a search folder in the extension dialog or save your SVG document first.")
            )

        file_index, lower_index = self._index_search_roots(
            search_roots, case_insensitive=self.options.case_insensitive
        )

        already_valid = []
        embedded_skipped = 0
        remote_skipped = 0
        no_ref = []
        relinked = []
        not_found = []
        ambiguities = []

        for node in images:
            node_id = node.get_id()
            raw_href = self._get_node_href(node)
            absref = node.get("sodipodi:absref")

            if not raw_href and not absref:
                no_ref.append(node_id)
                continue

            if raw_href and raw_href.strip().startswith("data:"):
                embedded_skipped += 1
                continue

            if raw_href and urllib.parse.urlsplit(raw_href).scheme in ("http", "https"):
                remote_skipped += 1
                continue

            existing_path = self._resolve_existing_path(raw_href, absref, doc_dir)
            if existing_path and not self.options.relink_all:
                already_valid.append((node_id, existing_path))
                continue

            filename, subpath_hint = self._extract_filename_and_hint(raw_href, absref)
            if not filename:
                no_ref.append(node_id)
                continue

            candidates = file_index.get(filename, [])
            if not candidates and self.options.case_insensitive:
                candidates = lower_index.get(filename.lower(), [])

            if not candidates:
                not_found.append((node_id, filename, raw_href or absref or ""))
                continue

            chosen_path, is_ambiguous = self._select_best_candidate(
                candidates, filename, subpath_hint, self.options.case_insensitive
            )

            if is_ambiguous:
                ambiguities.append((node_id, filename, chosen_path, len(candidates)))

            if not self.options.dry_run:
                try:
                    if self.options.embed_found:
                        self._embed_image(node, chosen_path)
                    else:
                        new_href = self._format_href(chosen_path, doc_dir, self.options.path_style)
                        self._update_node_href(node, new_href, chosen_path)
                except (OSError, IOError) as err:
                    not_found.append((node_id, filename, f"{chosen_path} (error reading file: {err})"))
                    continue

            relinked.append((node_id, filename, raw_href or absref or "", chosen_path))

        report = self._build_report(
            total_count=len(images),
            already_valid=already_valid,
            relinked=relinked,
            not_found=not_found,
            embedded_skipped=embedded_skipped,
            remote_skipped=remote_skipped,
            no_ref=no_ref,
            ambiguities=ambiguities,
            search_roots=search_roots,
            doc_dir=doc_dir,
        )

        inkex.errormsg(report)

    def _get_document_dir(self):
        """Determine directory containing the SVG document."""
        doc_dir = self.svg_path()
        if doc_dir and os.path.isdir(doc_dir):
            return os.path.abspath(doc_dir)

        doc_path = os.environ.get("DOCUMENT_PATH")
        if doc_path and os.path.isfile(doc_path):
            return os.path.abspath(os.path.dirname(doc_path))

        if self.options.input_file and os.path.isfile(self.options.input_file):
            candidate = os.path.dirname(os.path.abspath(self.options.input_file))
            if not candidate.startswith(("/tmp", "/var/tmp", "\\tmp")):
                return candidate

        return ""

    def _get_search_roots(self, doc_dir):
        """Collect list of directories to recursively search."""
        roots = []
        user_dir = self.options.search_dir
        if user_dir and user_dir.strip():
            expanded = os.path.expanduser(user_dir.strip())
            if os.path.isdir(expanded):
                roots.append(os.path.abspath(expanded))
            else:
                inkex.errormsg(_("Specified search directory does not exist: {}\n").format(expanded))

        if self.options.search_doc_dir and doc_dir and os.path.isdir(doc_dir):
            abs_doc = os.path.abspath(doc_dir)
            if abs_doc not in roots:
                roots.append(abs_doc)

        return roots

    @staticmethod
    def _index_search_roots(search_roots, case_insensitive=True):
        """Index all files in search roots recursively in one single pass."""
        exact_map = {}
        lower_map = {}
        visited = set()
        ignored_names = {
            ".git", ".svn", ".hg", "__pycache__", ".cache",
            "node_modules", ".Trash", ".trash"
        }

        for root in search_roots:
            real_root = os.path.realpath(root)
            if real_root in visited or not os.path.isdir(real_root):
                continue
            visited.add(real_root)

            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [
                    d for d in dirnames
                    if d not in ignored_names and not d.startswith(".")
                ]
                for fname in filenames:
                    full_path = os.path.join(dirpath, fname)
                    exact_map.setdefault(fname, []).append(full_path)
                    if case_insensitive:
                        lower_map.setdefault(fname.lower(), []).append(full_path)

        return exact_map, lower_map

    @staticmethod
    def _get_node_href(node):
        """Get image href from xlink:href or href."""
        return (
            node.get("xlink:href")
            or node.get("href")
            or node.get("{http://www.w3.org/1999/xlink}href")
        )

    @staticmethod
    def _parse_path_from_href(raw_href):
        """Convert an href or URI string into a clean filesystem path string."""
        if not raw_href:
            return ""
        parsed = urllib.parse.urlsplit(raw_href)
        if parsed.scheme == "file":
            return urllib.request.url2pathname(parsed.path)
        unquoted = urllib.parse.unquote(parsed.path if parsed.scheme == "" else raw_href)
        if unquoted.startswith("file://"):
            return urllib.request.url2pathname(unquoted[7:])
        return unquoted

    def _resolve_existing_path(self, raw_href, absref, doc_dir):
        """Check if image file already exists on disk at its current path."""
        parsed_path = self._parse_path_from_href(raw_href)
        if parsed_path:
            if os.path.isabs(parsed_path) and os.path.isfile(parsed_path):
                return os.path.abspath(parsed_path)
            if doc_dir:
                cand = os.path.normpath(os.path.join(doc_dir, parsed_path))
                if os.path.isfile(cand):
                    return os.path.abspath(cand)

        if absref and os.path.isabs(absref) and os.path.isfile(absref):
            return os.path.abspath(absref)

        return None

    def _extract_filename_and_hint(self, raw_href, absref):
        """Extract image basename and subpath hint from href and absref."""
        parsed = self._parse_path_from_href(raw_href)
        fname = os.path.basename(parsed) if parsed else ""
        if not fname and absref:
            fname = os.path.basename(absref)
        hint = parsed if parsed else (absref or "")
        return fname, hint

    @staticmethod
    def _select_best_candidate(candidates, target_filename, subpath_hint, case_insensitive):
        """Score candidate paths and pick the best match."""
        if len(candidates) == 1:
            return candidates[0], False

        def score(cand):
            val = 0
            base = os.path.basename(cand)
            if base == target_filename:
                val += 1000
            else:
                val += 500

            cand_norm = cand.replace("\\", "/").rstrip("/")
            hint_norm = subpath_hint.replace("\\", "/").strip("/")
            if hint_norm and "/" in hint_norm:
                hint_parts = [p for p in hint_norm.split("/") if p and p not in (".", "..")]
                cand_parts = [p for p in cand_norm.split("/") if p]
                matches = 0
                for p_h, p_c in zip(reversed(hint_parts), reversed(cand_parts)):
                    if (p_h if not case_insensitive else p_h.lower()) == (
                        p_c if not case_insensitive else p_c.lower()
                    ):
                        matches += 1
                    else:
                        break
                val += matches * 200

            val -= len(cand.split(os.sep))
            return val

        scored = [(cand, score(cand)) for cand in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)

        best_cand = scored[0][0]
        is_ambiguous = (
            len(scored) > 1 and scored[0][1] == scored[1][1]
        )
        return best_cand, is_ambiguous

    @staticmethod
    def _format_href(chosen_path, doc_dir, path_style):
        """Format the href as relative or absolute, using forward slashes for SVG."""
        abs_target = os.path.abspath(chosen_path)
        if path_style == "relative" and doc_dir:
            try:
                rel = os.path.relpath(abs_target, doc_dir)
                return rel.replace("\\", "/")
            except ValueError:
                return abs_target.replace("\\", "/")
        return abs_target.replace("\\", "/")

    @staticmethod
    def _update_node_href(node, new_href, chosen_path):
        """Set xlink:href, href, and sodipodi:absref attributes on SVG node."""
        node.set("xlink:href", new_href)
        if "href" in node.attrib:
            node.set("href", new_href)
        node.set("sodipodi:absref", os.path.abspath(chosen_path))

    def _embed_image(self, node, file_path):
        """Embed an external image file as Base64 data directly into SVG."""
        with open(file_path, "rb") as handle:
            data = handle.read()

        mime = self._get_mime_type(file_path, data[:32])
        encoded = base64.b64encode(data).decode("ascii")
        data_uri = f"data:{mime};base64,{encoded}"

        node.set("xlink:href", data_uri)
        if "href" in node.attrib:
            node.set("href", data_uri)
        if "sodipodi:absref" in node.attrib:
            del node.attrib["sodipodi:absref"]

    @staticmethod
    def _get_mime_type(file_path, header):
        """Detect MIME type from file header or file extension."""
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if header.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "image/webp"
        if header.startswith(b"BM"):
            return "image/bmp"
        if header.startswith((b"MM\x00*", b"II*\x00")):
            return "image/tiff"
        if b"ftypavif" in header[4:16]:
            return "image/avif"
        if header.strip().startswith((b"<svg", b"<?xml")):
            return "image/svg+xml"

        guessed, _ = mimetypes.guess_type(file_path)
        return guessed or "application/octet-stream"

    def _build_report(
        self,
        total_count,
        already_valid,
        relinked,
        not_found,
        embedded_skipped,
        remote_skipped,
        no_ref,
        ambiguities,
        search_roots,
        doc_dir,
    ):
        """Construct a detailed, clean report string for the user dialog."""
        lines = []
        if self.options.dry_run:
            lines.append(_("=== DRY RUN (No changes saved to SVG) ===\n"))
        elif self.options.embed_found:
            lines.append(_("=== EMBEDDED IMAGES INTO SVG ===\n"))
        else:
            lines.append(_("=== Fix Missing Images ===\n"))

        lines.append(_("Summary:"))
        lines.append(_("  • Total <image> elements checked: {}").format(total_count))
        lines.append(_("  • Successfully relinked: {}").format(len(relinked)))
        lines.append(_("  • Already linked correctly: {}").format(len(already_valid)))
        lines.append(_("  • Still missing (not found): {}").format(len(not_found)))

        if embedded_skipped:
            lines.append(_("  • Already embedded (skipped): {}").format(embedded_skipped))
        if remote_skipped:
            lines.append(_("  • Remote web URLs (skipped): {}").format(remote_skipped))
        if no_ref:
            lines.append(_("  • Empty image elements (skipped): {}").format(len(no_ref)))

        if relinked:
            action_verb = _("Would relink") if self.options.dry_run else (
                _("Embedded") if self.options.embed_found else _("Relinked")
            )
            lines.append(f"\n{action_verb} ({len(relinked)}):")
            for node_id, filename, old_ref, new_path in relinked:
                display_new = (
                    os.path.relpath(new_path, doc_dir)
                    if (doc_dir and self.options.path_style == "relative")
                    else new_path
                )
                lines.append(f'  ✓ "{filename}" [#{node_id}]\n    → {display_new}')

        if not_found:
            lines.append(f"\n" + _("Still Missing (not found in search folders) ({}):").format(len(not_found)))
            for node_id, filename, old_ref in not_found:
                lines.append(f'  ✗ "{filename}" [#{node_id}]')
                if old_ref:
                    lines.append(f"    Original path: {old_ref}")

        if ambiguities:
            lines.append(f"\n" + _("Multiple candidates found for:"))
            for node_id, filename, chosen_path, count in ambiguities:
                lines.append(
                    _("  ! \"{}\" [#{}] had {} matches; selected: {}").format(
                        filename, node_id, count, chosen_path
                    )
                )

        lines.append(f"\n" + _("Search folders searched recursively:"))
        for r in search_roots:
            lines.append(f"  • {r}")

        return "\n".join(lines)


if __name__ == "__main__":
    FixMissingImages().run()
