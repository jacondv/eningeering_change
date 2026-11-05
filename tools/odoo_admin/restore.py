"""Restoring a backup folder, as backup_odoo.bat writes them: <db>.dump + filestore.tar.gz.

Restoring never starts by removing anything: a backup goes into a new database
and a staging folder first, so a bad one leaves what's running as it was.
"""
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FILESTORE_NAME = "filestore.tar.gz"
FILESTORE_ROOT = "/var/lib/odoo/.local/share/Odoo/filestore"
VALID_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
# Windows' marks on a OneDrive file whose content is still only online.
ONLINE_ONLY = stat.FILE_ATTRIBUTE_OFFLINE | 0x00040000 | 0x00400000

# These shell scripts take only names validated above, so need no quoting,
# which wouldn't survive the trip through Windows' command line in one piece.
EXTRACT_SCRIPT = (
    "set -e; rm -rf $1/$3; mkdir -p $1/$3; tar xzf - -C $1/$3; test -d $1/$3/$2"
)
PUBLISH_SCRIPT = "set -e; mv $1/$3/$2 $1/$4; rm -rf $1/$3"
SWAP_SCRIPT = "set -e; if [ -d $1/$4 ]; then mv $1/$4 $1/$5; fi; mv $1/$3/$2 $1/$4; rm -rf $1/$3"
UNDO_SWAP_SCRIPT = "if [ -d $1/$3 ]; then rm -rf $1/$2; mv $1/$3 $1/$2; fi"
REMOVE_SCRIPT = "rm -rf $1/$2"


class RestoreError(Exception):
    pass


@dataclass
class BackupInfo:
    folder: Path
    dump: Path
    filestore: Path
    source_database: str
    online_only: list = field(default_factory=list)

    @property
    def size_mb(self):
        return (self.dump.stat().st_size + self.filestore.stat().st_size) / 1024 ** 2


def inspect_backup(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise RestoreError(f"Folder not found: {folder}.")
    dumps = list(folder.glob("*.dump"))
    if len(dumps) != 1:
        raise RestoreError(f"The folder must hold exactly 1 .dump file, found {len(dumps)}.")
    filestore = folder / FILESTORE_NAME
    if not filestore.is_file():
        raise RestoreError(f"The folder has no {FILESTORE_NAME}.")
    files = [dumps[0], filestore]
    online_only = [
        path.name for path in files if getattr(path.stat(), "st_file_attributes", 0) & ONLINE_ONLY
    ]
    return BackupInfo(folder, dumps[0], filestore, dumps[0].stem, online_only)


def verify_backup(stack, info):
    """Read both files through the tools that will restore them. Returns the
    number of objects the dump holds."""
    log = stack.runner.on_line
    log(f"Checking {info.dump.name}...")
    toc = stack.exec_db("pg_restore", "--list", stdin_path=info.dump, quiet=True, check=False)
    if toc.returncode != 0:
        raise RestoreError(f"The .dump file cannot be read: {toc.text}")
    objects = sum(1 for line in toc.lines if line and not line.startswith(";"))

    log(f"Checking {info.filestore.name}...")
    listing = stack.exec_odoo(
        "bash", "-c", "set -o pipefail; tar tzf - | cut -d/ -f1 | sort -u",
        stdin_path=info.filestore, quiet=True, check=False,
    )
    if listing.returncode != 0:
        raise RestoreError(f"The filestore file cannot be read: {listing.text}")
    if info.source_database not in listing.lines:
        raise RestoreError(f"The filestore does not contain folder {info.source_database}.")
    log(f"The backup is readable: {objects} objects in the dump.")
    return objects


def default_copy_name(source_database, now=None):
    # Not starting with the source's name, or a db_filter matching production's
    # name would match this copy too, and send users to the database selector.
    return f"restore_{source_database}_{_timestamp(now)}"


def check_copy_name(stack, name):
    _check_name(name)
    if name == stack.config.database:
        raise RestoreError("A copy cannot use the production database's name.")
    if stack.database_exists(name):
        raise RestoreError(f"Database {name} already exists. Choose another name.")


def restore_copy(stack, info, target):
    """Into a new database, with its crons and mail servers disabled, so it can't
    act like production. Never touches an existing database."""
    log = stack.runner.on_line
    _ensure_no_backup_running(stack)
    check_copy_name(stack, target)
    verify_backup(stack, info)
    stage = f".restoring_{target}"

    log(f"--- Creating database {target}")
    stack.exec_db("createdb", "-U", "odoo", target)
    try:
        log("--- Restoring the database")
        _restore_dump(stack, info, target, strict=False)
        log("--- Restoring the filestore")
        _extract_filestore(stack, info, stage)
        _odoo_script(stack, PUBLISH_SCRIPT, FILESTORE_ROOT, info.source_database, stage, target)
        log("--- Disabling the copy's crons and mail servers")
        stack.exec_odoo("odoo", "neutralize", "-d", target)
    except Exception:
        log("Error: removing what was created.")
        _cleanup(stack, target, stage)
        _odoo_script(stack, REMOVE_SCRIPT, FILESTORE_ROOT, target, check=False)
        raise
    summary = _summary(stack, target)
    log(f"--- Copy restored: {target} ({summary}).")
    return target


def restore_overwrite(stack, info, confirmed_name, now=None):
    """Replace production. Odoo only stops for the swap at the end, by which time
    the backup is restored and checked; what it replaces is kept under another name."""
    log = stack.runner.on_line
    database = stack.config.database
    if confirmed_name != database:
        raise RestoreError(f"The confirmation does not match {database}.")
    _ensure_no_backup_running(stack)
    verify_backup(stack, info)

    stamp = _timestamp(now)
    temp = f"restoring_{database}_{stamp}"
    keep = f"before_restore_{database}_{stamp}"
    stage = f".{temp}"
    for name in (temp, keep):
        _check_name(name)

    log("--- Safety backup of the current database")
    safety = _safety_backup(stack, stamp)
    log(f"Saved at: {safety}")

    log(f"--- Restoring into temporary database {temp}")
    stack.exec_db("createdb", "-U", "odoo", temp)
    try:
        _restore_dump(stack, info, temp, strict=True)
        summary = _summary(stack, temp)
        log(f"Temporary database: {summary}")
        _extract_filestore(stack, info, stage)
    except Exception:
        log("Error: the running database was not touched. Removing the temporary data.")
        _cleanup(stack, temp, stage)
        raise

    log("--- Stopping Odoo")
    stack.compose("stop", "odoo")
    try:
        _swap_database(stack, database, temp, keep)
        try:
            log("--- Swapping the filestore")
            _stopped_odoo_script(stack, SWAP_SCRIPT, FILESTORE_ROOT, info.source_database, stage, database, keep)
        except Exception:
            log("Filestore swap failed: putting the previous database and filestore back.")
            _stopped_odoo_script(stack, UNDO_SWAP_SCRIPT, FILESTORE_ROOT, database, keep, check=False)
            _swap_database(stack, database, keep, temp)
            raise
    except Exception:
        # `temp` only names the restored copy here, never what production runs on.
        stack.exec_db("dropdb", "-U", "odoo", "--if-exists", temp, check=False)
        _stopped_odoo_script(stack, REMOVE_SCRIPT, FILESTORE_ROOT, stage, check=False)
        raise
    finally:
        log("--- Starting Odoo")
        stack.compose("start", "odoo")
    stack.wait_healthy()
    log(f"--- Overwrite finished. Previous data kept as database and filestore {keep}, safety backup at {safety}.")
    return keep


def _check_name(name):
    if not VALID_DATABASE_NAME.match(name):
        raise RestoreError(f"Invalid database name: {name} (only a-z, 0-9 and _, up to 63 characters, starting with a letter).")


def _ensure_no_backup_running(stack):
    if stack.backup_in_progress():
        raise RestoreError("A backup is running. Wait for it to finish, then restore.")


def _timestamp(now=None):
    return (now or datetime.now()).strftime("%Y%m%d_%H%M%S")


def _restore_dump(stack, info, database, strict):
    result = stack.exec_db(
        "pg_restore", "-U", "odoo", "-d", database, "--no-owner", "--role=odoo",
        stdin_path=info.dump, check=False,
    )
    if result.returncode == 0:
        return
    if strict:
        raise RestoreError(f"pg_restore reported errors (code {result.returncode}), stopping. See the log above.")
    stack.runner.on_line(f"WARNING: pg_restore reported errors (code {result.returncode}). Check the log before trusting this copy.")


def _extract_filestore(stack, info, stage):
    stack.exec_odoo(
        "bash", "-c", EXTRACT_SCRIPT, "_", FILESTORE_ROOT, info.source_database, stage,
        stdin_path=info.filestore,
    )


def _odoo_script(stack, script, *args, **kwargs):
    return stack.exec_odoo("bash", "-c", script, "_", *args, **kwargs)


def _stopped_odoo_script(stack, script, *args, **kwargs):
    # The filestore is only reachable from a container, and Odoo's is stopped.
    return stack.compose(
        "run", "--rm", "--no-deps", "-T", "-u", "odoo", "--entrypoint", "bash", "odoo",
        "-c", script, "_", *args, **kwargs,
    )


def _summary(stack, database):
    """Raises if the database isn't an Odoo one that has modules and users."""
    modules = stack.sql(database, "SELECT count(*) FROM ir_module_module WHERE state = 'installed'")[0]
    users = stack.sql(database, "SELECT count(*) FROM res_users")[0]
    if modules == "0" or users == "0":
        raise RestoreError(f"Database {database} looks wrong: {modules} modules, {users} users.")
    return f"{modules} modules installed, {users} users"


def _cleanup(stack, database, stage):
    # check=False: the error that brought us here is the one to report.
    stack.exec_db("dropdb", "-U", "odoo", "--if-exists", database, check=False)
    _odoo_script(stack, REMOVE_SCRIPT, FILESTORE_ROOT, stage, check=False)


def _safety_backup(stack, stamp):
    database = stack.config.database
    folder = stack.config.safety_backup_root / f"{database}_{stamp}"
    dump = folder / f"{database}.dump"
    filestore = folder / FILESTORE_NAME
    folder.mkdir(parents=True)
    stack.exec_db("pg_dump", "-U", "odoo", "-Fc", database, stdout_path=dump)
    stack.exec_odoo("tar", "czf", "-", "-C", FILESTORE_ROOT, database, stdout_path=filestore)
    if dump.stat().st_size < 1000:
        raise RestoreError(f"The safety backup is too small, it may be broken: {dump}")
    return folder


def _swap_database(stack, current, replacement, keep):
    """`current` becomes `keep`, `replacement` becomes `current`, both or neither."""
    stack.runner.on_line(f"--- Swapping databases: {current} -> {keep}, {replacement} -> {current}")
    stack.sql(
        "postgres",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname IN ('{current}', '{replacement}') AND pid <> pg_backend_pid()",
    )
    stack.sql(
        "postgres",
        f"BEGIN; ALTER DATABASE {current} RENAME TO {keep}; ALTER DATABASE {replacement} RENAME TO {current}; COMMIT;",
    )
