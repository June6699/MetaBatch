from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metabatch.gene_reader import discover_gene_files, normalize_patterns


class DiscoverGeneFilesTests(unittest.TestCase):
    def _make_root(self, files: list[str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Zfhx3\n", encoding="utf-8")
        return root

    def test_txt_pattern_only_matches_txt_when_xlsx_coexists(self) -> None:
        root = self._make_root(
            [
                "list_A.txt",
                "list_A.xlsx",
                "list_B.txt",
                "list_B.xlsx",
            ]
        )
        matched = discover_gene_files(root, "*.txt")
        self.assertEqual([p.name for p in matched], ["list_A.txt", "list_B.txt"])

    def test_empty_pattern_matches_all_supported_types(self) -> None:
        root = self._make_root(
            ["list_A.txt", "list_B.csv", "list_C.xlsx", "ignore.docx"]
        )
        matched = discover_gene_files(root)
        self.assertEqual(
            [p.name for p in matched],
            ["list_A.txt", "list_B.csv", "list_C.xlsx"],
        )

    def test_multiple_patterns_separated_by_semicolon(self) -> None:
        root = self._make_root(
            ["list_A.txt", "list_B.csv", "list_C.xlsx", "list_D.txt"]
        )
        matched = discover_gene_files(root, "*.txt;*.csv")
        self.assertEqual(
            [p.name for p in matched],
            ["list_A.txt", "list_B.csv", "list_D.txt"],
        )

    def test_pattern_matching_is_case_insensitive(self) -> None:
        root = self._make_root(["list_A.TXT", "list_B.Txt"])
        matched = discover_gene_files(root, "*.txt")
        self.assertEqual([p.name for p in matched], ["list_A.TXT", "list_B.Txt"])

    def test_name_glob_pattern(self) -> None:
        root = self._make_root(["gene_A.txt", "gene_B.txt", "other.txt"])
        matched = discover_gene_files(root, "*gene*")
        self.assertEqual([p.name for p in matched], ["gene_A.txt", "gene_B.txt"])

    def test_generated_metascape_results_are_excluded(self) -> None:
        root = self._make_root(["list.txt", "list_metascape.xlsx"])
        matched = discover_gene_files(root)
        self.assertEqual([p.name for p in matched], ["list.txt"])


class NormalizePatternsTests(unittest.TestCase):
    def test_string_split_by_semicolon_and_comma(self) -> None:
        self.assertEqual(normalize_patterns(" *.txt ; *.csv,"), ["*.txt", "*.csv"])

    def test_sequence_input(self) -> None:
        self.assertEqual(normalize_patterns(["*.txt", " ", "*.csv"]), ["*.txt", "*.csv"])

    def test_none_and_empty(self) -> None:
        self.assertEqual(normalize_patterns(None), [])
        self.assertEqual(normalize_patterns(""), [])
        self.assertEqual(normalize_patterns(" ; , "), [])


if __name__ == "__main__":
    unittest.main()
