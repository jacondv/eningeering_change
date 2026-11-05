"""Odoo Admin: updates production and restores its backups. See README.md."""
import ctypes
import sys
from pathlib import Path

# Run as `pythonw path\to\main.py`, wherever from.
sys.path.insert(0, str(Path(__file__).parent))

MB_ICONERROR = 0x10


def fail(message):
    # pythonw has no console, so a plain error would vanish without a trace.
    ctypes.windll.user32.MessageBoxW(None, message, "Odoo Admin", MB_ICONERROR)
    sys.exit(1)


def main():
    try:
        import tkinter as tk
    except ImportError:
        fail("This Python has no tkinter. Run install.bat, or reinstall Python from python.org with \"tcl/tk and IDLE\" ticked.")

    from activity import ActivityLog, SingleInstance
    from app import App
    from config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as error:
        fail(str(error))

    instance = SingleInstance()
    if not instance.acquire():
        fail("Odoo Admin is already open.")

    root = tk.Tk()
    App(root, config, ActivityLog())
    root.mainloop()


if __name__ == "__main__":
    main()
