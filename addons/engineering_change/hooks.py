def post_init_hook(env):
    """Grant every Internal User the base 'General User' access level of this app,
    so the app menu and basic access work out of the box without a manual
    per-user group assignment step. Must be done via ORM write (not a static XML
    <record> update) because base.group_user is a noupdate=True core record and
    XML data updates to it are silently skipped on install/upgrade.
    """
    group_user = env.ref('base.group_user', raise_if_not_found=False)
    group_ec_user = env.ref('engineering_change.group_ec_user', raise_if_not_found=False)
    if group_user and group_ec_user and group_ec_user not in group_user.implied_ids:
        group_user.write({'implied_ids': [(4, group_ec_user.id)]})
