"""A Runner that records commands instead of running them."""
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from commands import CommandError, Result  # noqa: E402
from config import Config  # noqa: E402
from stack import Stack  # noqa: E402

CONFIG = Config(
    project_dir=Path("C:/project"),
    database="prod",
    branch="main",
    odoo_url="http://localhost:1",
    backup_script=Path("C:/scripts/backup.bat"),
    backup_root=Path("C:/backups"),
    safety_backup_root=Path("C:/safety"),
)


class FakeRunner:
    """`responses`: (substring of the command, Result), the first match answers;
    a command matching `failing` exits with 1."""

    def __init__(self, responses=(), failing=()):
        self.responses = list(responses)
        self.failing = list(failing)
        self.commands = []
        self.logged = []

    def on_line(self, line):
        self.logged.append(line)

    def run(self, args, *, stdin_path=None, stdout_path=None, check=True, quiet=False):
        command = " ".join(args)
        self.commands.append(command)
        if stdout_path:
            Path(stdout_path).write_bytes(b"x" * 2000)
        if any(pattern in command for pattern in self.failing):
            if check:
                raise CommandError(args, 1, [])
            return Result(1, [])
        for pattern, result in self.responses:
            if pattern in command:
                return result
        return Result(0, [])

    def index(self, pattern):
        """Position of the first command containing `pattern`."""
        return next(i for i, command in enumerate(self.commands) if pattern in command)

    def ran(self, pattern):
        return any(pattern in command for command in self.commands)


def make_stack(runner, **config_changes):
    stack = Stack(runner, replace(CONFIG, **config_changes), sleep=lambda seconds: None)
    stack.wait_healthy = lambda *args, **kwargs: runner.commands.append("HEALTH")
    return stack


NO_BACKUP_RUNNING = ("application_name = 'pg_dump'", Result(0, ["0"]))
