def migrate(cr, version):
    """Documents now go Draft -> In Review -> Released. The ones that exist start as Drafts (nobody is
    locked out mid-work), and their older Revs stay as history. How many Revs to keep is no longer a setting."""
    cr.execute("UPDATE jacon_office_document SET state = 'draft' WHERE state IS NULL")
    cr.execute("DELETE FROM ir_config_parameter WHERE key = 'jacon_office.versions_to_keep'")
