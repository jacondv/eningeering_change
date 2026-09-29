def post_init_hook(env):
    # base.group_user is noupdate=True, so an XML implied_ids edit would be
    # silently skipped. Linking here covers future Internal Users; existing
    # ones are added explicitly since implied_ids doesn't back-propagate.
    group_user = env.ref('base.group_user')
    group_ps_user = env.ref('jacon_product_support.group_ps_user')
    if group_ps_user not in group_user.implied_ids:
        group_user.write({'implied_ids': [(4, group_ps_user.id)]})
    missing = group_user.user_ids - group_ps_user.user_ids
    if missing:
        group_ps_user.write({'user_ids': [(4, user.id) for user in missing]})
