# Odoo Admin

A small window on the production machine to update Odoo and restore backups,
instead of typing the commands. Backups stay on Windows Task Scheduler.

## Setup

1. Run `install.bat`. It finds a Python 3.10+ that has tkinter, or installs one
   through winget, and creates `venv/` from it. It also creates `config.json`
   from `config.example.json` if there is none. Safe to run again.
2. Correct `config.json` for the machine, above all `database`.
3. Create a Desktop shortcut to `run.bat`.

The tool only uses Python's standard library, so there is nothing else to install.
`venv/`, `config.json` and `logs/` stay on the machine, they are not committed.

## Update tab

**Check** fetches and lists the new commits and every addon, ticking the
installed ones whose changes need an upgrade (anything but `static/` and
`tests/`). **Update** then runs: backup, fast-forward to the commit that was
checked, image build if `Dockerfile`, `docker-compose.yml` or `requirements.txt`
changed, module update, restart, health check. An error stops it there, and the
steps after it have not run.

It refuses to run on another branch, with tracked files edited by hand, or while
a backup is running.

## Restore tab

Pick a backup folder (`<db>.dump` + `filestore.tar.gz`): both files are read
through first, by the tools that will restore them.

- **Copy:** into a new database, with crons and mail servers neutralized. Its
  default name doesn't start with production's, so that `db_filter` doesn't match
  it and send users to the database selector. That also means it can't be opened
  on the web as is: the tool checks it by counting its modules and users.
- **Overwrite production:** takes typing the database's name.
  1. Safety backup into `safety_backup_root`, which backup pruning doesn't touch.
  2. Restore into a temporary database and staging folder, and check them. Any
     error up to here leaves production as it was, without having stopped Odoo.
  3. Stop Odoo, swap the database and filestore, start Odoo.

  The replaced data stays as database and filestore folder
  `before_restore_<db>_<time>`, to delete by hand once no longer needed.

## Tests

    py -3 -m unittest discover -s tools/odoo_admin/tests

Everything is logged to `logs/<year-month>.log`.
