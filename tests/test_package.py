"""Tests for the template tooling: python3 -m unittest discover tests"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import package  # noqa: E402
import rastpkg  # noqa: E402


class Template(unittest.TestCase):
    def test_package_json_produces_a_valid_manifest(self):
        pkg = json.loads((ROOT / "package.json").read_text())
        version = pkg["source"]["version"]
        m = json.loads(json.dumps(pkg["manifest"]).replace("{version}", version))
        m.update(version=version, revision=1, artifacts=[{
            "target": "linux-x86_64",
            "url": f"https://github.com/owner/repo/releases/download/v{version}-1/x.tar.gz",
            "sha256": "0" * 64, "size": 1, "format": "tar.gz", "stripComponents": 1,
            "provenance": {"kind": "built", "source": pkg["source"]["url"], "sourceSha256": pkg["source"]["sha256"]},
        }])
        rastpkg.validate_manifest(m)
        self.assertEqual(set(pkg["targets"]), set(rastpkg.KNOWN_TARGETS))

    def test_tags(self):
        self.assertEqual(package.parse_tag("v5.4.9-1"), ("5.4.9", 1))
        self.assertEqual(package.parse_tag("v1.2.3-rc1-2"), ("1.2.3-rc1", 2))
        for bad in ("5.4.9-1", "v5.4.9", "v5.4.9-0"):
            with self.assertRaises(SystemExit):
                package.parse_tag(bad)

    def test_schema_matches_known_targets(self):
        schema = json.loads((ROOT / "schema/rast-package.schema.json").read_text())
        targets = schema["properties"]["artifacts"]["items"]["properties"]["target"]["enum"]
        self.assertEqual(tuple(targets), rastpkg.KNOWN_TARGETS)


if __name__ == "__main__":
    unittest.main()
