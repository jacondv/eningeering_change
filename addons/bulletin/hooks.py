from odoo import SUPERUSER_ID, api


def post_init_hook(env):
    # base.group_user (Internal User) is a noupdate=True record, so a plain
    # XML <record> write to its implied_ids is silently skipped on install/
    # upgrade - this has to run as Python instead. Linking Bulletin User
    # here immediately grants it to every existing Internal User too (Odoo
    # propagates implied_ids additions to a group's current members on
    # write), not just future ones.
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    group_user = env.ref('base.group_user')
    group_bulletin_user = env.ref('bulletin.group_bulletin_user')
    if group_bulletin_user not in group_user.implied_ids:
        group_user.write({'implied_ids': [(4, group_bulletin_user.id)]})
    # Adding to implied_ids only affects future group membership changes,
    # not users already in base.group_user - add those explicitly too.
    missing = group_user.user_ids - group_bulletin_user.user_ids
    if missing:
        group_bulletin_user.write({'user_ids': [(4, u.id) for u in missing]})
