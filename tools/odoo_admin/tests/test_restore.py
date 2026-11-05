import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fakes import NO_BACKUP_RUNNING, FakeRunner, make_stack

from commands import CommandError, Result
from restore import (
    RestoreError, default_copy_name, inspect_backup, restore_copy, restore_overwrite, verify_backup,
)

NOW = datetime(2026, 11, 5, 9, 30, 0)
TEMP = "restoring_prod_20261105_093000"
KEEP = "before_restore_prod_20261105_093000"
HEALTHY_RESPONSES = [
    NO_BACKUP_RUNNING,
    ("datname = ", Result(0, [])),  # no database of that name yet
    ("tar tzf", Result(0, ["src"])),
    ("pg_restore --list", Result(0, [";", "1; 2 TABLE"])),
    ("ir_module_module", Result(0, ["12"])),
    ("res_users", Result(0, ["3"])),
]


class BackupFolderTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def test_a_complete_folder(self):
        (self.folder / "jacon_plm.dump").write_bytes(b"x")
        (self.folder / "filestore.tar.gz").write_bytes(b"x")
        self.assertEqual(inspect_backup(self.folder).source_database, "jacon_plm")

    def test_missing_folder(self):
        with self.assertRaisesRegex(RestoreError, "not found"):
            inspect_backup(self.folder / "nope")

    def test_missing_dump(self):
        (self.folder / "filestore.tar.gz").write_bytes(b"x")
        with self.assertRaisesRegex(RestoreError, ".dump"):
            inspect_backup(self.folder)

    def test_several_dumps_are_not_guessed_between(self):
        (self.folder / "a.dump").write_bytes(b"x")
        (self.folder / "b.dump").write_bytes(b"x")
        (self.folder / "filestore.tar.gz").write_bytes(b"x")
        with self.assertRaisesRegex(RestoreError, "found 2"):
            inspect_backup(self.folder)

    def test_missing_filestore(self):
        (self.folder / "a.dump").write_bytes(b"x")
        with self.assertRaisesRegex(RestoreError, "filestore"):
            inspect_backup(self.folder)


class RestoreCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        backup = self.root / "backup"
        backup.mkdir()
        (backup / "src.dump").write_bytes(b"x")
        (backup / "filestore.tar.gz").write_bytes(b"x")
        self.info = inspect_backup(backup)
        self.runner = FakeRunner(HEALTHY_RESPONSES)
        self.stack = make_stack(self.runner, safety_backup_root=self.root / "safety")


class VerifyBackupTest(RestoreCase):
    def test_counts_the_objects(self):
        self.assertEqual(verify_backup(self.stack, self.info), 1)

    def test_unreadable_dump(self):
        self.runner.failing = ["pg_restore --list"]
        with self.assertRaisesRegex(RestoreError, "dump"):
            verify_backup(self.stack, self.info)

    def test_unreadable_filestore(self):
        self.runner.failing = ["tar tzf"]
        with self.assertRaisesRegex(RestoreError, "ilestore"):
            verify_backup(self.stack, self.info)

    def test_filestore_of_another_database(self):
        self.runner.responses = [("tar tzf", Result(0, ["other"]))] + self.runner.responses
        with self.assertRaisesRegex(RestoreError, "does not contain"):
            verify_backup(self.stack, self.info)


class RestoreCopyTest(RestoreCase):
    def test_default_name_does_not_start_with_the_source(self):
        name = default_copy_name("jacon_plm", NOW)
        self.assertEqual(name, "restore_jacon_plm_20261105_093000")
        self.assertFalse(name.startswith("jacon_plm"))

    def test_restores_and_neutralizes(self):
        restore_copy(self.stack, self.info, "copy1")
        order = ["pg_restore --list", "createdb -U odoo copy1", "pg_restore -U odoo -d copy1", "tar xzf", "neutralize -d copy1"]
        positions = [self.runner.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))

    def test_never_drops_anything_on_success(self):
        restore_copy(self.stack, self.info, "copy1")
        self.assertFalse(self.runner.ran("dropdb"))

    def test_refuses_production_and_existing_names(self):
        with self.assertRaisesRegex(RestoreError, "production"):
            restore_copy(self.stack, self.info, "prod")
        self.runner.responses = [("datname = ", Result(0, ["1"]))] + self.runner.responses
        with self.assertRaisesRegex(RestoreError, "already exists"):
            restore_copy(self.stack, self.info, "taken")
        self.assertFalse(self.runner.ran("createdb"))

    def test_refuses_names_that_are_not_plain(self):
        for name in ("Upper", "with space", "a;drop", "1abc", "x" * 64, ""):
            with self.assertRaisesRegex(RestoreError, "Invalid"):
                restore_copy(self.stack, self.info, name)

    def test_failure_removes_only_what_it_created(self):
        self.runner.failing = ["tar xzf"]
        with self.assertRaises(CommandError):
            restore_copy(self.stack, self.info, "copy1")
        self.assertTrue(self.runner.ran("dropdb -U odoo --if-exists copy1"))
        self.assertFalse(self.runner.ran("--if-exists prod"))

    def test_pg_restore_warnings_are_reported_and_kept_going(self):
        self.runner.failing = ["pg_restore -U odoo"]
        restore_copy(self.stack, self.info, "copy1")
        self.assertTrue(any("WARNING" in line for line in self.runner.logged))


class RestoreOverwriteTest(RestoreCase):
    def overwrite(self):
        return restore_overwrite(self.stack, self.info, "prod", now=NOW)

    def test_steps_run_in_a_safe_order(self):
        self.assertEqual(self.overwrite(), KEEP)
        order = [
            "pg_dump -U odoo -Fc prod",
            f"createdb -U odoo {TEMP}",
            f"pg_restore -U odoo -d {TEMP}",
            "tar xzf",
            "stop odoo",
            f"ALTER DATABASE prod RENAME TO {KEEP}",
            "--entrypoint bash odoo",
            "start odoo",
            "HEALTH",
        ]
        positions = [self.runner.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))

    def test_renames_are_one_transaction(self):
        self.overwrite()
        swap = self.runner.commands[self.runner.index("ALTER DATABASE")]
        self.assertIn(f"BEGIN; ALTER DATABASE prod RENAME TO {KEEP}; ALTER DATABASE {TEMP} RENAME TO prod; COMMIT;", swap)

    def test_nothing_is_ever_dropped_on_success(self):
        self.overwrite()
        self.assertFalse(self.runner.ran("dropdb"))

    def test_wrong_confirmation_does_nothing(self):
        with self.assertRaisesRegex(RestoreError, "confirmation"):
            restore_overwrite(self.stack, self.info, "PROD", now=NOW)
        self.assertEqual(self.runner.commands, [])

    def test_safety_backup_failure_stops_before_anything_else(self):
        self.runner.failing = ["pg_dump"]
        with self.assertRaises(CommandError):
            self.overwrite()
        self.assertFalse(self.runner.ran("createdb"))
        self.assertFalse(self.runner.ran("stop odoo"))

    def test_any_pg_restore_error_keeps_production_running(self):
        self.runner.failing = [f"pg_restore -U odoo -d {TEMP}"]
        with self.assertRaisesRegex(RestoreError, "pg_restore"):
            self.overwrite()
        self.assertFalse(self.runner.ran("stop odoo"))
        self.assertFalse(self.runner.ran("ALTER DATABASE"))
        self.assertTrue(self.runner.ran(f"dropdb -U odoo --if-exists {TEMP}"))
        self.assertFalse(self.runner.ran("--if-exists prod"))

    def test_a_restored_database_that_looks_wrong_keeps_production_running(self):
        self.runner.responses = [("ir_module_module", Result(0, ["0"]))] + self.runner.responses
        with self.assertRaisesRegex(RestoreError, "looks wrong"):
            self.overwrite()
        self.assertFalse(self.runner.ran("stop odoo"))

    def test_bad_filestore_keeps_production_running(self):
        self.runner.failing = ["tar xzf"]
        with self.assertRaises(CommandError):
            self.overwrite()
        self.assertFalse(self.runner.ran("stop odoo"))

    def test_failed_rename_restarts_odoo_and_keeps_production(self):
        self.runner.failing = ["ALTER DATABASE"]
        with self.assertRaises(CommandError):
            self.overwrite()
        self.assertTrue(self.runner.ran("start odoo"))
        self.assertFalse(self.runner.ran("--if-exists prod"))
        self.assertFalse(self.runner.ran(f"--if-exists {KEEP}"))

    def test_failed_filestore_swap_puts_the_database_back(self):
        self.runner.failing = ["mv $1/$4 $1/$5"]
        with self.assertRaises(CommandError):
            self.overwrite()
        forward = self.runner.index(f"ALTER DATABASE prod RENAME TO {KEEP}")
        back = self.runner.index(f"ALTER DATABASE prod RENAME TO {TEMP}; ALTER DATABASE {KEEP} RENAME TO prod")
        self.assertLess(forward, back)
        self.assertLess(back, self.runner.index("start odoo"))
        self.assertFalse(self.runner.ran("--if-exists prod"))

    def test_safety_backup_is_written_outside_the_backup_root(self):
        self.overwrite()
        folder = self.root / "safety" / "prod_20261105_093000"
        self.assertTrue((folder / "prod.dump").is_file())
        self.assertTrue((folder / "filestore.tar.gz").is_file())


if __name__ == "__main__":
    unittest.main()
