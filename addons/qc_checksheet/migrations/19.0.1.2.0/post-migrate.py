"""The default Create & Edit access used to miss anyone who is an Internal User
only through another group, such as an Administrator. Only those users are
touched here, so an access an admin removed by hand on purpose stays removed.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group_user = env.ref('base.group_user')
    missed = group_user.all_user_ids - group_user.user_ids
    env.ref('qc_checksheet.group_qc_author').write({'user_ids': [(4, user.id) for user in missed]})
