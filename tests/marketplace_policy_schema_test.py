from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import CompanyReviewedSource
from agent_artifacts.configuration.schema import (
    organization_policy_bytes,
    parse_organization_policy,
)
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok


class MarketplacePolicySchemaTest(unittest.TestCase):
    def test_exact_company_reviewed_source_identities_are_strict_canonical_policy(self) -> None:
        document = b"""{
          "schema_version": 1,
          "company_reviewed_sources": [
            {"source_id":"company-registry","git_host":"Git.Company.Example","repository":"agents/company-registry.git"}
          ]
        }"""

        parsed = parse_organization_policy(document)

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            parsed.value.company_reviewed_sources,
            (
                CompanyReviewedSource(
                    SourceId("company-registry"),
                    "git.company.example",
                    "agents/company-registry",
                ),
            ),
        )
        self.assertEqual(
            parse_organization_policy(organization_policy_bytes(parsed.value)),
            parsed,
        )

    def test_invalid_or_duplicate_company_reviewed_identities_fail_closed(self) -> None:
        invalid = (
            '{"schema_version":1,"company_reviewed_sources":{}}',
            '{"schema_version":1,"company_reviewed_sources":[{}]}',
            '{"schema_version":1,"company_reviewed_sources":[{"source_id":"Bad_ID","git_host":"example.test","repository":"team/repo"}]}',
            '{"schema_version":1,"company_reviewed_sources":[{"source_id":"registry","git_host":"https://example.test","repository":"team/repo"}]}',
            '{"schema_version":1,"company_reviewed_sources":[{"source_id":"registry","git_host":"example.test","repository":"../repo"}]}',
            '{"schema_version":1,"company_reviewed_sources":[{"source_id":"registry","git_host":"example.test","repository":"team/repo"},{"source_id":"registry","git_host":"EXAMPLE.TEST","repository":"team/repo.git"}]}',
        )
        for document in invalid:
            with self.subTest(document=document):
                self.assertIsInstance(parse_organization_policy(document), Err)


if __name__ == "__main__":
    unittest.main()
