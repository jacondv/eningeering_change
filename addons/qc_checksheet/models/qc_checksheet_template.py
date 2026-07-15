from odoo import fields, models

CHECKSHEET_TYPES = [
    ('standard', 'Standard'),
    ('panel_sticker', 'Panel & Sticker'),
]


class QcChecksheetTemplate(models.Model):
    """Branding + shared table structure only - no Inspection Groups/Items or
    Panel Lines here (see techspec §2.1). Content is authored per check sheet,
    either from scratch or copied from a previous one.
    """
    _name = 'qc.checksheet.template'
    _description = 'QC Check Sheet Template'
    _order = 'name'

    name = fields.Char(required=True)
    checksheet_type = fields.Selection(CHECKSHEET_TYPES, required=True, default='standard')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    default_approval_position_ids = fields.One2many(
        'qc.checksheet.template.approval', 'template_id', string='Default Approval Positions')


class QcChecksheetTemplateApproval(models.Model):
    _name = 'qc.checksheet.template.approval'
    _description = 'QC Check Sheet Template Default Approval Position'
    _order = 'sequence, id'

    template_id = fields.Many2one('qc.checksheet.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    position = fields.Char(required=True)
