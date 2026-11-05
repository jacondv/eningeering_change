"""What's shared by every operation: its log on disk, and only one at a time."""
import getpass
import msvcrt
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).with_name("logs")


class ActivityLog:
    """Appends to logs/<year-month>.log, flushed at every line so that it's all
    there even if the tool dies halfway through an operation."""

    def __init__(self, log_dir=LOG_DIR):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{datetime.now():%Y-%m}.log"
        self.user = getpass.getuser()

    def write(self, line):
        with open(self.path, "a", encoding="utf-8") as file:
            file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{self.user}] {line}\n")


class SingleInstance:
    """Held for as long as the process lives: Windows releases it if it dies."""

    def __init__(self, log_dir=LOG_DIR):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.file = open(log_dir / ".lock", "w")

    def acquire(self):
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
