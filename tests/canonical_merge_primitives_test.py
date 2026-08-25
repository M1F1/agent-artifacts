"""The two pure helpers the canonical merge path is built from.

`_render_template` and `_descend` decide what an MCP or hook entry actually becomes on disk, and
their edges — a placeholder that must stay a number, a dotted path that crosses a scalar — are
invisible in an end-to-end install that happens to use neither. They were once covered by the
retired legacy merge engine's own tests; these pin the canonical implementations directly.
"""

from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.installation.application import _descend, _render_template


class RenderTemplateTest(unittest.TestCase):
    def test_a_whole_field_placeholder_keeps_the_value_type(self) -> None:
        # ``"${port}"`` is how a template refers to a number; stringifying it would write
        # ``"8080"`` into the harness config and the harness would reject its own schema.
        rendered = _render_template(
            {"port": "${port}", "tls": "${tls}"}, {"port": 8080, "tls": True}
        )

        self.assertEqual(rendered, {"port": 8080, "tls": True})

    def test_a_placeholder_inside_a_larger_string_is_stringified(self) -> None:
        rendered = _render_template("${dir}/run.sh", {"dir": "/opt/hooks"})

        self.assertEqual(rendered, "/opt/hooks/run.sh")

    def test_nested_objects_and_lists_render_all_the_way_down(self) -> None:
        rendered = _render_template(
            {"env": {"LABEL": "${label}"}, "args": ["--root", "${dir}"]},
            {"label": "abc", "dir": "/srv"},
        )

        self.assertEqual(rendered, {"env": {"LABEL": "abc"}, "args": ["--root", "/srv"]})

    def test_an_unknown_field_renders_as_empty_rather_than_leaking_the_placeholder(self) -> None:
        # Leaving ``${missing}`` in place would ship a literal placeholder to the harness; an
        # empty string is the visible, harmless failure.
        rendered = _render_template("prefix-${missing}-suffix", {})

        self.assertEqual(rendered, "prefix--suffix")


class DescendTest(unittest.TestCase):
    def test_a_dotted_path_creates_the_objects_it_names(self) -> None:
        root: dict[str, object] = {}

        node = _descend(root, "a.b.c", force=False)

        assert isinstance(node, Ok), node
        node.value["installed"] = True
        self.assertEqual(root, {"a": {"b": {"c": {"installed": True}}}})

    def test_descending_keeps_the_siblings_already_on_the_path(self) -> None:
        root: dict[str, object] = {"a": {"keep": 1}}

        node = _descend(root, "a.b", force=False)

        assert isinstance(node, Ok), node
        self.assertEqual(root, {"a": {"keep": 1, "b": {}}})

    def test_crossing_a_scalar_is_refused_and_force_replaces_it(self) -> None:
        refused = _descend({"a": "not-an-object"}, "a.b", force=False)

        assert isinstance(refused, Err), refused
        self.assertIn("crosses non-object field", refused.diagnostics[0].message)

        root: dict[str, object] = {"a": "not-an-object"}
        forced = _descend(root, "a.b", force=True)

        assert isinstance(forced, Ok), forced
        self.assertEqual(root, {"a": {"b": {}}})

    def test_an_empty_path_is_the_root_itself(self) -> None:
        root: dict[str, object] = {"existing": 1}

        node = _descend(root, "", force=False)

        assert isinstance(node, Ok), node
        self.assertIs(node.value, root)


if __name__ == "__main__":
    unittest.main()
