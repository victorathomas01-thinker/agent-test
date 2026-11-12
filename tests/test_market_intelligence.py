"""Synthetic regression tests; no real personal data or external job boards."""
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.market_intelligence import (
    export_csvs, require_private, snapshot, source_connection, utc_stamp,
)


def source_fixture(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, source TEXT, company TEXT,
            title TEXT, location TEXT, last_seen TEXT,
            status TEXT, reason TEXT, notes TEXT
        );
        CREATE TABLE job_details (
            job_id TEXT PRIMARY KEY, published_at TEXT,
            workplace TEXT, employment_type TEXT, salary TEXT
        );
        CREATE TABLE web_checks (
            job_id TEXT PRIMARY KEY, verification TEXT
        );
        CREATE TABLE attempts (
            id INTEGER PRIMARY KEY, job_id TEXT, details TEXT
        );
        CREATE TABLE verified_facts (key TEXT, value TEXT);
    """)
    con.executemany(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("greenhouse:demo:101", "greenhouse", "Example Health", "IT Support Intern",
             "Charlotte, NC", "2026-11-10T10:00:00+00:00", "rejected", "PRIVATE_GPA_REASON", "PRIVATE_NOTES"),
            ("lever:demo:102", "lever", '=INJECT("x")', "Business Intelligence Analyst",
             "Charlotte, NC", "2026-09-01T10:00:00+00:00", "interview", "PRIVATE_REASON", "PRIVATE_EMAIL"),
            ("manual:private:103", "manual", "Private Referral", "Student Assistant",
             "Charlotte", "2026-11-10T10:00:00+00:00", "submitted", "PRIVATE_REASON", "PRIVATE_NOTES"),
        ],
    )
    con.executemany(
        "INSERT INTO job_details VALUES (?,?,?,?,?)",
        [
            ("greenhouse:demo:101", "2026-11-01", "hybrid", "internship", "$22 / hr"),
            ("lever:demo:102", "", "remote", "fulltime", ""),
            ("manual:private:103", "", "", "", "private salary"),
        ],
    )
    con.execute("INSERT INTO web_checks VALUES ('greenhouse:demo:101','structured')")
    con.execute("INSERT INTO attempts VALUES (1,'greenhouse:demo:101','PRIVATE_APPLICATION_HISTORY')")
    con.execute("INSERT INTO verified_facts VALUES ('applicant_email','PRIVATE_EMAIL')")
    con.commit()
    con.close()


class MarketIntelligenceTests(unittest.TestCase):
    def test_readonly_snapshot_and_privacy_safe_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source, warehouse, output = (folder / name for name in (
                "source.sqlite3", "warehouse.sqlite3", "export"))
            source_fixture(source)
            before = source.read_bytes()
            first = snapshot(source, warehouse, "2026-11-12T00:00:00+00:00")
            self.assertEqual(first["records"], 2)
            second = snapshot(source, warehouse, "2026-11-13T00:00:00+00:00")
            self.assertEqual(second["records"], 2)
            self.assertEqual(source.read_bytes(), before, "Never mutate the agent's source database")

            paths = export_csvs(warehouse, output)
            self.assertEqual(len(paths), 3)
            all_export_text = "\n".join(path.read_text(encoding="utf-8") for path in paths.values())
            for forbidden in (
                "PRIVATE_GPA_REASON", "PRIVATE_NOTES", "PRIVATE_EMAIL",
                "PRIVATE_APPLICATION_HISTORY", "Private Referral", "manual:private:103",
                "submitted", "interview", "rejected",
            ):
                self.assertNotIn(forbidden, all_export_text)
            self.assertIn("'=INJECT", all_export_text, "Spreadsheet formula prefix must be neutralized")

            with (output / "market_postings.csv").open(encoding="utf-8", newline="") as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual(len(records), 4)
            self.assertEqual({row["category"] for row in records},
                             {"IT/application support", "Data/analytics"})
            self.assertEqual(sum(int(row["new_to_collector"]) for row in records), 2)
            self.assertEqual(sum(int(row["seen_within_7_days"]) for row in records), 2)
            self.assertEqual(sum(int(row["salary_disclosed"]) for row in records), 2)
            self.assertEqual(len({row["posting_key"] for row in records}), 2)

            with sqlite3.connect(warehouse) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM market_category_summary").fetchone()[0], 4)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM market_first_collected").fetchone()[0], 2)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0], 4)

    def test_invalid_or_missing_source_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            missing = folder / "missing.sqlite3"
            with self.assertRaises(FileNotFoundError):
                source_connection(missing)
            self.assertFalse(missing.exists())
            invalid = folder / "wrong.sqlite3"
            with sqlite3.connect(invalid) as con:
                con.execute("CREATE TABLE other (x INTEGER)")
            destination = folder / "warehouse.sqlite3"
            with self.assertRaisesRegex(ValueError, "required job tables"):
                snapshot(invalid, destination)
            self.assertFalse(destination.exists())

    def test_reject_bad_times_and_source_warehouse_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            src = folder / "source.sqlite3"
            source_fixture(src)
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                snapshot(src, folder / "market.sqlite3", "2026-11-12")
            with self.assertRaisesRegex(ValueError, "must differ"):
                snapshot(src, src, "2026-11-12T12:00:00+00:00")
            self.assertIsNone(utc_stamp("not a real date"))

    def test_real_export_cli_must_stay_under_gitignored_private(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "private"):
                require_private(Path(temp) / "leak.csv")


if __name__ == "__main__":
    unittest.main()
