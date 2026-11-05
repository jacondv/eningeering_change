"""The running system: the git checkout, its docker compose services and Odoo."""
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class StackError(Exception):
    pass


@dataclass
class Overview:
    commit: str
    branch: str
    services: str
    free_disk_gb: float


class Stack:
    def __init__(self, runner, config, sleep=time.sleep):
        self.runner = runner
        self.config = config
        self.sleep = sleep

    # Git

    def git(self, *args, **kwargs):
        return self.runner.run(["git", *args], **kwargs)

    def git_value(self, *args):
        return self.git(*args, quiet=True).text

    # Docker compose

    def compose(self, *args, **kwargs):
        return self.runner.run(["docker", "compose", *args], **kwargs)

    def exec_db(self, *args, **kwargs):
        return self.compose("exec", "-T", "db", *args, **kwargs)

    def exec_odoo(self, *args, **kwargs):
        return self.compose("exec", "-T", "-u", "odoo", "odoo", *args, **kwargs)

    def sql(self, database, query, **kwargs):
        kwargs.setdefault("quiet", True)
        return self.exec_db(
            "psql", "-U", "odoo", "-d", database, "-v", "ON_ERROR_STOP=1", "-Atc", query, **kwargs
        ).lines

    def database_exists(self, name):
        return bool(self.sql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{name}'"))

    def backup_in_progress(self):
        """Whether a pg_dump is running, such as the scheduled backup's."""
        return self.sql("postgres", "SELECT count(*) FROM pg_stat_activity WHERE application_name = 'pg_dump'") != ["0"]

    def overview(self):
        services = self.compose("ps", "--all", "--format", "{{.Service}}: {{.State}}", quiet=True)
        return Overview(
            commit=self.git_value("log", "-1", "--format=%h %s"),
            branch=self.git_value("branch", "--show-current"),
            services=", ".join(services.lines),
            free_disk_gb=shutil.disk_usage(self.config.project_dir).free / 1024 ** 3,
        )

    # Odoo

    def addon_names(self):
        addons = self.config.project_dir / "addons"
        return sorted(path.parent.name for path in addons.glob("*/__manifest__.py"))

    def module_states(self, names):
        quoted = ", ".join(f"'{name}'" for name in names)
        rows = self.sql(self.config.database, f"SELECT name, state FROM ir_module_module WHERE name IN ({quoted})")
        return dict(row.split("|") for row in rows)

    def update_modules(self, database, upgrade=(), install=(), **kwargs):
        args = ["odoo", "-d", database]
        if upgrade:
            args += ["-u", ",".join(upgrade)]
        if install:
            args += ["-i", ",".join(install)]
        # The running server already holds Odoo's own ports.
        return self.exec_odoo(*args, "--stop-after-init", "--http-port=8899", "--gevent-port=8902", **kwargs)

    def wait_healthy(self, timeout=180, interval=3):
        url = f"{self.config.odoo_url}/web/health"
        self.runner.on_line(f"Waiting for Odoo at {url}...")
        waited = 0
        while waited < timeout:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.status == 200:
                        self.runner.on_line("Odoo is responding.")
                        return
            except (urllib.error.URLError, OSError):
                pass  # Still starting.
            self.sleep(interval)
            waited += interval
        raise StackError(f"Odoo did not respond within {timeout} seconds.")
