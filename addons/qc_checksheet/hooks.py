def grant_default_access(env):
    """Every Internal User can view check sheets and, by default, create and
    edit them. View is implied by Internal User, which must be done via ORM
    write (not a static XML <record> update) because base.group_user is a
    noupdate=True core record and XML data updates to it are silently skipped
    on install/upgrade.

    Create & Edit is granted to each user directly, plus through Odoo's
    "Default Access Rights" for future users, and not implied by Internal
    User: an implied group can't be unticked for a single user, and an admin
    needs to be able to do that.
    """
    group_user = env.ref('base.group_user')
    group_qc_user = env.ref('qc_checksheet.group_qc_user')
    group_qc_author = env.ref('qc_checksheet.group_qc_author')
    if group_qc_user not in group_user.implied_ids:
        group_user.write({'implied_ids': [(4, group_qc_user.id)]})
    group_qc_author.write({'user_ids': [(4, user.id) for user in group_user.all_user_ids]})
    default_group = env.ref('base.default_user_group', raise_if_not_found=False)
    if default_group:
        default_group.write({'implied_ids': [(4, group_qc_author.id)]})


def post_init_hook(env):
    grant_default_access(env)
