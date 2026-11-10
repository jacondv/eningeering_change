from odoo import fields, models


class EquipmentModel(models.Model):
    """A Model owns its check sheets: they are written and revised here, and
    every Job of the Model prints them."""
    _inherit = 'equipment.model'

    qc_checksheet_progress = fields.Char(
        string='QC Check Sheets', compute='_compute_qc_checksheet_progress',
        groups='qc_checksheet.group_qc_user',
        help="Required Check Sheet Types with a Released sheet, out of all required Types.")

    def _compute_qc_checksheet_progress(self):
        # Active required Types only, like the Model QC page. A Model's sheet counts once Released; a Job's
        # (see project.project) also once it printed one, since its pinned Revision may be Superseded.
        required_types = self.env['qc.checksheet.type']._required_types()
        released_by_model = self.env['qc.checksheet.share']._ready_types(self, required_types)
        for model in self:
            model.qc_checksheet_progress = f'{len(released_by_model[model.id])}/{len(required_types)}'

    def action_open_qc_model(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.model',
            'name': f'QC: {self.display_name}',
            'context': {'active_id': self.id},
        }
