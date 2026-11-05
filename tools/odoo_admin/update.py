"""Bringing production up to the newest commit and upgrading modules."""
import re
from dataclasses import dataclass, field

UPGRADE = "upgrade"
RESTART = "restart"
INSTALLED = "installed"

# Changing these takes a new image rather than just a restart.
IMAGE_FILES = {"Dockerfile", "docker-compose.yml", "requirements.txt"}
# What needs no upgrade: assets are served fresh after a restart, the rest never loads.
NO_UPGRADE_DIRS = {"static", "tests"}
ODOO_LOG_ERROR = re.compile(r"^\d{4}-\d{2}-\d{2} \S+ \d+ (ERROR|CRITICAL) ")


class UpdateError(Exception):
    pass


@dataclass
class Module:
    name: str
    state: str
    change: str | None  # UPGRADE, RESTART or None

    @property
    def installed(self):
        return self.state == INSTALLED

    @property
    def selected_by_default(self):
        return self.installed and self.change == UPGRADE


@dataclass
class UpdateStatus:
    current: str
    target: str
    commits: list = field(default_factory=list)
    changed_files: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    modules: list = field(default_factory=list)

    @property
    def has_new_code(self):
        return self.current != self.target

    @property
    def needs_image_build(self):
        return any(path in IMAGE_FILES for path in self.changed_files)

    @property
    def changes_addons(self):
        return any(path.startswith("addons/") for path in self.changed_files)


def classify_changes(changed_files):
    """{module: UPGRADE or RESTART} for the addons those files belong to."""
    changes = {}
    for path in changed_files:
        parts = path.split("/")
        if parts[0] != "addons" or len(parts) < 3:
            continue
        module, inner = parts[1], parts[2]
        needs_upgrade = inner not in NO_UPGRADE_DIRS and not path.endswith(".md")
        if needs_upgrade:
            changes[module] = UPGRADE
        else:
            changes.setdefault(module, RESTART)
    return changes


def build_modules(names, states, changes):
    """The list to choose from, the ones with changes first."""
    modules = [Module(name, states.get(name, "uninstalled"), changes.get(name)) for name in names]
    rank = {UPGRADE: 0, RESTART: 1, None: 2}
    return sorted(modules, key=lambda module: (rank[module.change], module.name))


def check_for_updates(stack):
    branch = stack.config.branch
    stack.git("fetch", "origin", branch)
    current = stack.git_value("rev-parse", "HEAD")
    target = stack.git_value("rev-parse", f"origin/{branch}")
    status = UpdateStatus(current, target)

    active_branch = stack.git_value("branch", "--show-current")
    if active_branch != branch:
        status.blockers.append(f"This machine is on branch {active_branch or '(detached)'}, not {branch}.")
    modified = stack.git("status", "--porcelain", "--untracked-files=no", quiet=True).lines
    if modified:
        status.blockers.append("Tracked files edited by hand: " + ", ".join(line[3:] for line in modified))
    if stack.git("merge-base", "--is-ancestor", "HEAD", target, quiet=True, check=False).returncode != 0:
        status.blockers.append(f"The running commit is not part of origin/{branch}, so it cannot fast-forward.")

    if status.has_new_code:
        status.commits = stack.git("log", "--oneline", f"{current}..{target}", quiet=True).lines
        status.changed_files = stack.git("diff", "--name-only", current, target, quiet=True).lines

    names = stack.addon_names()
    status.modules = build_modules(names, stack.module_states(names), classify_changes(status.changed_files))
    return status


def run_update(stack, status, selected_names, backup=True):
    """Backup, pull, build if needed, update modules, restart, check. An error
    stops it right there: anything after that step hasn't happened.
    """
    log = stack.runner.on_line
    if status.blockers:
        raise UpdateError("Cannot update: " + " ".join(status.blockers))
    if stack.backup_in_progress():
        raise UpdateError("A backup is running. Wait for it to finish, then update.")

    by_name = {module.name: module for module in status.modules}
    selected = [by_name[name] for name in selected_names]
    upgrade = [module.name for module in selected if module.installed]
    install = [module.name for module in selected if not module.installed]
    log(f"Commit before the update: {status.current}")

    if backup:
        log("--- Backup")
        stack.runner.run([str(stack.config.backup_script), stack.config.database])

    if status.has_new_code:
        log("--- Getting the new code")
        # The commit that was reviewed, not whatever is newest by now.
        stack.git("merge", "--ff-only", status.target)

    if status.needs_image_build:
        log("--- Rebuilding the image")
        stack.compose("up", "-d", "--build")

    if selected:
        log(f"--- Updating modules: upgrade={upgrade} install={install}")
        _update_modules(stack, upgrade, install)

    if selected or status.changes_addons or status.needs_image_build:
        log("--- Restarting Odoo")
        stack.compose("restart", "odoo")
        stack.wait_healthy()
    else:
        log("Nothing needs a restart.")
    log("--- Update finished.")


def _update_modules(stack, upgrade, install):
    result = stack.update_modules(stack.config.database, upgrade, install, check=False)
    errors = [line for line in result.lines if ODOO_LOG_ERROR.match(line)]
    # Either on its own counts: Odoo can log a failed module and still exit with 0.
    if result.returncode != 0 or errors:
        first = errors[0] if errors else "no ERROR line in the log"
        raise UpdateError(f"Module update failed (code {result.returncode}), Odoo was not restarted. First error: {first}")
