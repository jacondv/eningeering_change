from odoo import _, api, fields, models

from .qc_checksheet import GROUP_AUTHOR

CHANGE_SEARCH_LIMIT = 20
# A Draft request has no number yet and a Rejected one goes nowhere.
NOT_LINKABLE_STATES = ('draft', 'canceled')
# Still being carried out: what the Job QC page flags.
FINISHED_STATES = ('draft', 'done', 'canceled')


class QcChecksheet(models.Model):
    """Engineering Changes a Revision comes from: picked when the Revision is
    created, kept on it, and printed in its Revision History."""
    _inherit = 'qc.checksheet'

    change_request_ids = fields.Many2many(
        'engineering.change', 'qc_checksheet_change_rel', 'checksheet_id', 'change_id',
        string='Engineering Changes', copy=False,
        domain=[('state', 'not in', list(NOT_LINKABLE_STATES))],
        help="The Engineering Changes this Revision comes from. Printed with its line in the Revision History.")

    @api.model
    def _change_summary(self, change):
        states = dict(change._fields['state']._description_selection(self.env))
        return {
            'id': change.id,
            'name': change.name,
            'title': change.title or '',
            'state_label': states.get(change.state, ''),
        }

    def _history_change_names(self, revision):
        """The Engineering Changes of Revision number `revision` of this sheet, for the Revision History."""
        self.ensure_one()
        rev = self.root_id.revision_ids.filtered(lambda r: r.revision == revision)[:1]
        return ', '.join(rev.change_request_ids.mapped('name'))

    def editor_search_changes(self, term=''):
        """Engineering Changes to link to this sheet, those affecting its Job or Model first."""
        self.ensure_one()
        Change = self.env['engineering.change']
        # Stored roll-ups of the Actions: land any pending recompute before searching on them.
        Change.flush_model(['affected_project_ids', 'affected_model_ids'])
        domain = [('state', 'not in', list(NOT_LINKABLE_STATES))]
        term = (term or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('title', 'ilike', term)]
        affecting_domain = []
        if self.job_number:
            affecting_domain.append(('affected_project_ids', 'in', self.job_number.id))
        model = self.job_number.sudo().model_id
        if model:
            affecting_domain.append(('affected_model_ids', 'in', model.id))
        affecting = Change.browse()
        if affecting_domain:
            affecting = Change.search(
                domain + ['|'] * (len(affecting_domain) - 1) + affecting_domain,
                limit=CHANGE_SEARCH_LIMIT, order='id desc')
        others = Change.browse()
        if len(affecting) < CHANGE_SEARCH_LIMIT:
            others = Change.search(
                domain + [('id', 'not in', affecting.ids)],
                limit=CHANGE_SEARCH_LIMIT - len(affecting), order='id desc')
        return [dict(self._change_summary(change), affects=change in affecting) for change in affecting + others]

    def editor_set_changes(self, change_ids):
        """Replace the Engineering Changes of this Draft Revision."""
        self.ensure_one()
        self._check_group(GROUP_AUTHOR)
        self._check_state('draft')
        changes = self.env['engineering.change'].browse(change_ids or []).exists()
        self.write({'change_request_ids': [(6, 0, changes.ids)]})
        return [self._change_summary(change) for change in changes]

    def editor_load(self):
        data = super().editor_load()
        data['changes'] = [self._change_summary(change) for change in self.change_request_ids]
        return data

    @api.model
    def job_overview(self, job_id):
        data = super().job_overview(job_id)
        self.env['engineering.change'].flush_model(['affected_project_ids'])
        running = self.env['engineering.change'].search([
            ('affected_project_ids', 'in', job_id), ('state', 'not in', list(FINISHED_STATES)),
        ], order='id desc')
        data['changes'] = [self._change_summary(change) for change in running]
        return data


class EngineeringChange(models.Model):
    _inherit = 'engineering.change'

    qc_checksheet_ids = fields.Many2many(
        'qc.checksheet', 'qc_checksheet_change_rel', 'change_id', 'checksheet_id',
        string='QC Check Sheets', copy=False, groups='qc_checksheet.group_qc_user')
    qc_checksheet_count = fields.Integer(
        compute='_compute_qc_checksheet_count', groups='qc_checksheet.group_qc_user')

    @api.depends('qc_checksheet_ids')
    def _compute_qc_checksheet_count(self):
        for rec in self:
            rec.qc_checksheet_count = len(rec.qc_checksheet_ids)

    def action_view_qc_checksheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("QC Check Sheets: %s", self.name),
            'res_model': 'qc.checksheet',
            'view_mode': 'list,form',
            'domain': [('change_request_ids', 'in', self.id)],
            'context': {'create': False},
        }
