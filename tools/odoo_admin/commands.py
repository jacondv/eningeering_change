"""Runs external commands, handing their output over line by line as it comes."""
import os
import subprocess
from dataclasses import dataclass


class CommandError(Exception):
    def __init__(self, args, returncode, lines):
        self.args_run = args
        self.returncode = returncode
        self.lines = lines
        # The last line: a quiet command's output is nowhere else to be seen.
        reason = f"\n{lines[-1]}" if lines else ""
        super().__init__(f"Command failed (code {returncode}): {subprocess.list2cmdline(args)}{reason}")


@dataclass
class Result:
    returncode: int
    lines: list

    @property
    def text(self):
        return "\n".join(self.lines).strip()


class Runner:
    def __init__(self, cwd, on_line=lambda line: None):
        self.cwd = cwd
        self.on_line = on_line

    def run(self, args, *, stdin_path=None, stdout_path=None, check=True, quiet=False):
        """Run `args`. `stdin_path`/`stdout_path` connect a file directly to the
        process rather than through Python, so that a backup's binary content
        reaches it untouched. `quiet` keeps the command out of the log, for the
        status queries that aren't part of an operation.
        """
        if not quiet:
            self.on_line(f"$ {subprocess.list2cmdline(args)}")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        stdout = open(stdout_path, "wb") if stdout_path else subprocess.PIPE
        lines = []
        try:
            process = subprocess.Popen(
                args,
                cwd=self.cwd,
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE if stdout_path else subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with process:
                for raw in process.stderr if stdout_path else process.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    lines.append(line)
                    if not quiet:
                        self.on_line(line)
        finally:
            if stdin_path:
                stdin.close()
            if stdout_path:
                stdout.close()
        if check and process.returncode != 0:
            raise CommandError(args, process.returncode, lines)
        return Result(process.returncode, lines)
