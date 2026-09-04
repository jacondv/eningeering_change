from . import models
from . import wizard


def migrate_last_update_status(env):
    """Runs automatically on every install/upgrade of this module (see
    'post_init_hook' in __manifest__.py) - no manual step needed on any
    environment. project.project.last_update_status and
    project.update.status used to allow core's on_track/at_risk/off_track/
    done/to_define values; models/project_project.py and
    models/project_update.py now restrict both Selections to just
    in_progress/on_hold/cancelled/eol. Existing rows still holding one of
    the dropped values are moved to 'in_progress' (the new equivalent of
    'to_define'/a normally-running project) via direct SQL, bypassing the
    ORM so this doesn't spuriously create project.update records or get
    blocked by the write() permission guard in project_project.py.
    Idempotent: re-running (e.g. a later upgrade with no new stale rows)
    simply matches zero rows.
    """
    env.cr.execute("""
        UPDATE project_update SET status = 'in_progress'
        WHERE status IN ('on_track', 'at_risk', 'off_track', 'done')
    """)
    env.cr.execute("""
        UPDATE project_project SET last_update_status = 'in_progress'
        WHERE last_update_status IN ('to_define', 'on_track', 'at_risk', 'off_track', 'done')
    """)
