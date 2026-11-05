import unittest

from fakes import NO_BACKUP_RUNNING, FakeRunner, make_stack

from commands import CommandError, Result
from update import (
    RESTART, UPGRADE, Module, UpdateError, UpdateStatus, build_modules, classify_changes, run_update,
)

OLD, NEW = "a" * 40, "b" * 40


def status(changed_files=("addons/one/models/x.py",), blockers=(), new_code=True):
    return UpdateStatus(
        current=OLD,
        target=NEW if new_code else OLD,
        changed_files=list(changed_files),
        blockers=list(blockers),
        modules=[Module("one", "installed", UPGRADE), Module("two", "uninstalled", None)],
    )


class ClassifyChangesTest(unittest.TestCase):
    def test_python_and_views_need_an_upgrade(self):
        self.assertEqual(classify_changes(["addons/one/models/x.py", "addons/two/views/y.xml"]),
                         {"one": UPGRADE, "two": UPGRADE})

    def test_assets_and_tests_only_need_a_restart(self):
        self.assertEqual(classify_changes(["addons/one/static/src/a.js", "addons/two/tests/t.py", "addons/three/README.md"]),
                         {"one": RESTART, "two": RESTART, "three": RESTART})

    def test_an_upgrade_wins_whichever_file_comes_first(self):
        for files in (["addons/one/static/a.js", "addons/one/__manifest__.py"],
                      ["addons/one/__manifest__.py", "addons/one/static/a.js"]):
            self.assertEqual(classify_changes(files), {"one": UPGRADE})

    def test_files_outside_a_module_are_ignored(self):
        self.assertEqual(classify_changes(["Scripts/x.bat", "addons/README.md", "tools/odoo_admin/main.py"]), {})


class BuildModulesTest(unittest.TestCase):
    def test_changed_first_and_only_installed_upgrades_preselected(self):
        modules = build_modules(
            ["a_same", "b_asset", "c_new", "d_code"],
            {"a_same": "installed", "b_asset": "installed", "d_code": "installed"},
            {"b_asset": RESTART, "c_new": UPGRADE, "d_code": UPGRADE},
        )
        self.assertEqual([module.name for module in modules], ["c_new", "d_code", "b_asset", "a_same"])
        self.assertEqual([module.name for module in modules if module.selected_by_default], ["d_code"])
        self.assertEqual(modules[0].state, "uninstalled")


class RunUpdateTest(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner([NO_BACKUP_RUNNING])
        self.stack = make_stack(self.runner)

    def test_steps_run_in_order(self):
        run_update(self.stack, status(), ["one"])
        order = ["backup.bat", f"merge --ff-only {NEW}", "odoo -d prod -u one", "restart odoo", "HEALTH"]
        positions = [self.runner.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))

    def test_uninstalled_modules_are_installed_and_not_upgraded(self):
        run_update(self.stack, status(), ["two"])
        self.assertTrue(self.runner.ran("odoo -d prod -i two"))
        self.assertFalse(self.runner.ran("-u two"))

    def test_module_update_keeps_off_the_running_servers_ports(self):
        run_update(self.stack, status(), ["one"])
        self.assertTrue(self.runner.ran("--stop-after-init --http-port=8899 --gevent-port=8902"))

    def test_backup_can_be_skipped(self):
        run_update(self.stack, status(), ["one"], backup=False)
        self.assertFalse(self.runner.ran("backup.bat"))

    def test_failed_backup_stops_before_touching_the_code(self):
        self.runner.failing = ["backup.bat"]
        with self.assertRaises(CommandError):
            run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("merge"))

    def test_failed_pull_stops_before_modules(self):
        self.runner.failing = ["merge --ff-only"]
        with self.assertRaises(CommandError):
            run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("--stop-after-init"))

    def test_failed_module_update_does_not_restart(self):
        self.runner.failing = ["odoo -d prod"]
        with self.assertRaisesRegex(UpdateError, "code 1"):
            run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("restart"))

    def test_error_logged_with_a_clean_exit_counts_as_failure(self):
        line = "2026-11-05 01:00:00,000 1 ERROR prod odoo.modules.registry: Failed to load registry"
        self.runner.responses.insert(0, ("odoo -d prod", Result(0, ["ok", line])))
        with self.assertRaisesRegex(UpdateError, "Failed to load registry"):
            run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("restart"))

    def test_other_output_mentioning_error_is_not_a_failure(self):
        line = "<string>:38: (ERROR/3) Unexpected indentation."
        self.runner.responses.insert(0, ("odoo -d prod", Result(0, [line])))
        run_update(self.stack, status(), ["one"])
        self.assertTrue(self.runner.ran("restart"))

    def test_changed_image_files_build_before_updating_modules(self):
        run_update(self.stack, status(["Dockerfile"]), ["one"])
        self.assertLess(self.runner.index("up -d --build"), self.runner.index("odoo -d prod"))

    def test_no_build_otherwise(self):
        run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("--build"))

    def test_no_restart_when_nothing_in_odoo_changed(self):
        run_update(self.stack, status(["tools/odoo_admin/main.py"]), [])
        self.assertTrue(self.runner.ran("merge"))
        self.assertFalse(self.runner.ran("restart"))

    def test_asset_change_restarts_even_with_nothing_selected(self):
        run_update(self.stack, status(["addons/one/static/a.js"]), [])
        self.assertTrue(self.runner.ran("restart odoo"))
        self.assertFalse(self.runner.ran("--stop-after-init"))

    def test_modules_can_be_updated_without_new_code(self):
        run_update(self.stack, status([], new_code=False), ["one"])
        self.assertFalse(self.runner.ran("merge"))
        self.assertTrue(self.runner.ran("odoo -d prod -u one"))

    def test_blockers_stop_everything(self):
        with self.assertRaisesRegex(UpdateError, "edited by hand"):
            run_update(self.stack, status(blockers=["Tracked files edited by hand."]), ["one"])
        self.assertEqual(self.runner.commands, [])

    def test_a_running_backup_stops_everything(self):
        self.runner.responses = [("application_name = 'pg_dump'", Result(0, ["1"]))]
        with self.assertRaisesRegex(UpdateError, "backup"):
            run_update(self.stack, status(), ["one"])
        self.assertFalse(self.runner.ran("merge"))


if __name__ == "__main__":
    unittest.main()
