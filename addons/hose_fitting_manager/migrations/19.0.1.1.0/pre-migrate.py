def migrate(cr, version):
    """Hose And Fitting Config's Fitting 1/Fitting 2 lists become one list.
    Fitting 1's list is the one kept; Fitting 2's rows are dropped, as are
    repeats within Fitting 1 (same Fitting + Ferrule) so the new
    no-duplicates check holds. The `slot` column goes too - left behind it
    would still be NOT NULL and block every new option.
    """
    cr.execute("DELETE FROM hose_fitting_manager_config_fitting_option WHERE slot = '2'")
    cr.execute("""
        DELETE FROM hose_fitting_manager_config_fitting_option option
         USING hose_fitting_manager_config_fitting_option kept
         WHERE kept.config_id = option.config_id
           AND kept.fitting_id = option.fitting_id
           AND kept.ferrule_id IS NOT DISTINCT FROM option.ferrule_id
           AND kept.id < option.id
    """)
    cr.execute("ALTER TABLE hose_fitting_manager_config_fitting_option DROP COLUMN IF EXISTS slot")
