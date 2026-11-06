"""Every Check Sheet Type already in use starts as Required for every Job."""


def migrate(cr, version):
    cr.execute("UPDATE qc_checksheet_type SET required = TRUE WHERE required IS NULL")
