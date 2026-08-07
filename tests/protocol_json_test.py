"""P01 contracts for strict immutable JSON and schema diagnostics."""

from __future__ import annotations

import dataclasses
import unittest


def _unwrap(result):
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


def _codes(result) -> tuple[str, ...]:
    from agent_artifacts.domain.result import Err

    if not isinstance(result, Err):
        raise AssertionError(f"expected Err, got {result!r}")
    return tuple(diagnostic.code.value for diagnostic in result.diagnostics)


class StrictJsonTest(unittest.TestCase):
    def test_parse_is_immutable_and_canonicalizes_object_order(self):
        from agent_artifacts.protocol.json import JsonObject, canonical_json_bytes, parse_json

        first = _unwrap(parse_json('{"z": [true, null], "a": "żółć"}'))
        second = _unwrap(parse_json(b'{"a":"\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87","z":[true,null]}'))

        self.assertIsInstance(first, JsonObject)
        self.assertEqual(first, second)
        self.assertEqual(
            canonical_json_bytes(first),
            b'{"a":"\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87","z":[true,null]}\n',
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.entries = ()

    def test_duplicate_keys_floats_constants_and_out_of_range_integers_have_stable_codes(self):
        from agent_artifacts.protocol.json import parse_json

        cases = (
            ('{"a": 1, "a": 2}', "protocol-json-duplicate-key"),
            ('{"value": 1.5}', "protocol-json-float"),
            ('{"value": NaN}', "protocol-json-invalid"),
            (str(2**63), "protocol-json-integer-range"),
            (str(-(2**63) - 1), "protocol-json-integer-range"),
            ("9" * 5000, "protocol-json-integer-range"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_codes(parse_json(raw)), (expected,))

        self.assertEqual(_unwrap(parse_json(str(-(2**63)))), -(2**63))
        self.assertEqual(_unwrap(parse_json(str(2**63 - 1))), 2**63 - 1)

    def test_invalid_utf8_surrogates_depth_and_string_bounds_fail_closed(self):
        from agent_artifacts.protocol.json import parse_json

        self.assertEqual(_codes(parse_json(b'"\xff"')), ("protocol-json-unicode",))
        self.assertEqual(_codes(parse_json('"\\ud800"')), ("protocol-json-unicode",))
        self.assertEqual(
            _codes(parse_json("[[[0]]]", max_depth=2)),
            ("protocol-json-depth",),
        )
        self.assertEqual(
            _codes(parse_json('"abcd"', max_string_length=3)),
            ("protocol-json-string-length",),
        )


class SchemaPrimitiveTest(unittest.TestCase):
    def test_required_unknown_and_namespaced_extension_fields_accumulate(self):
        from agent_artifacts.protocol.json import JsonObject, parse_json
        from agent_artifacts.protocol.schema import validate_object_fields

        document = _unwrap(
            parse_json('{"known": 1, "extra": 2, "bad extension": 3, "Com.acme.preview": 4}')
        )
        self.assertIsInstance(document, JsonObject)
        result = validate_object_fields(
            document,
            required=frozenset({"required"}),
            optional=frozenset({"known"}),
            allow_extensions=True,
        )
        self.assertEqual(
            _codes(result),
            (
                "protocol-schema-extension-key",
                "protocol-schema-extension-key",
                "protocol-schema-missing-field",
                "protocol-schema-unknown-field",
            ),
        )

        extended = _unwrap(parse_json('{"required": 1, "com.acme.preview": true}'))
        self.assertEqual(
            _unwrap(
                validate_object_fields(
                    extended,
                    required=frozenset({"required"}),
                    allow_extensions=True,
                )
            ),
            extended,
        )

    def test_schema_type_helpers_report_pointer_aware_diagnostics(self):
        from agent_artifacts.domain.diagnostics import SourceLocation
        from agent_artifacts.domain.identifiers import SourceAlias
        from agent_artifacts.domain.result import Err
        from agent_artifacts.protocol.json import parse_json
        from agent_artifacts.protocol.schema import expect_object, expect_string

        location = SourceLocation(SourceAlias("company"), "aart-source.json", "/display_name")
        wrong_object = expect_object(_unwrap(parse_json("[]")), location=location)
        wrong_string = expect_string(_unwrap(parse_json("42")), location=location)

        for result in (wrong_object, wrong_string):
            self.assertIsInstance(result, Err)
            assert isinstance(result, Err)
            self.assertEqual(result.diagnostics[0].code.value, "protocol-schema-type")
            self.assertEqual(result.diagnostics[0].location, location)


if __name__ == "__main__":
    unittest.main()
