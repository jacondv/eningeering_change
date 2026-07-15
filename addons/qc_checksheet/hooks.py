def post_init_hook(env):
    """Grant every Internal User this app's single access group, so the menu
    and basic access work out of the box without a manual per-user group
    assignment step. Must be done via ORM write (not a static XML <record>
    update) because base.group_user is a noupdate=True core record and XML
    data updates to it are silently skipped on install/upgrade.
    """
    group_user = env.ref('base.group_user', raise_if_not_found=False)
    group_qc_user = env.ref('qc_checksheet.group_qc_user', raise_if_not_found=False)
    if group_user and group_qc_user and group_qc_user not in group_user.implied_ids:
        group_user.write({'implied_ids': [(4, group_qc_user.id)]})
