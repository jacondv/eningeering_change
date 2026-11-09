def migrate(cr, version):
    """Check sheets now belong to a Model instead of a Job. A sheet left from
    before takes its Job's Model, so the upgrade can go on with it; the old
    Job column is dropped by the upgrade afterwards.

    Several Jobs of one Model used to hold their own sheet of the same Type,
    which a Model can't: the upgrade stops, leaving everything as it was,
    rather than pick one of them and silently delete the others.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'qc_checksheet' AND column_name = 'job_number'
    """)
    if not cr.fetchone():
        return
    cr.execute("ALTER TABLE qc_checksheet ADD COLUMN IF NOT EXISTS model_id integer")
    cr.execute("""
        UPDATE qc_checksheet sheet
           SET model_id = job.model_id
          FROM project_project job
         WHERE job.id = sheet.job_number AND sheet.model_id IS NULL
    """)
    cr.execute("""
        SELECT count(*) FROM (
            SELECT 1 FROM qc_checksheet
             WHERE model_id IS NOT NULL
             GROUP BY model_id, type_id, revision
            HAVING count(*) > 1
        ) clash
    """)
    clashes = cr.fetchone()[0]
    if clashes:
        raise Exception(
            "QC Check Sheet upgrade stopped: check sheets now belong to a Model, one per Type, "
            f"but {clashes} Model/Type/Revision combination(s) have a sheet on several Jobs. "
            "Delete the old Job check sheets first (QC Check Sheet > Check Sheets, remove the "
            "Active Revisions filter, select all, Delete - as a QC Administrator), then upgrade again. "
            "Nothing was changed.")
