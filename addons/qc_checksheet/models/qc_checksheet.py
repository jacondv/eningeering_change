from odoo import _, api, fields, models
from odoo.exceptions import UserError

CHECKSHEET_TYPES = [
    ('standard', 'Standard'),
    ('panel_sticker', 'Panel & Sticker'),
]


class QcChecksheet(models.Model):
    _name = 'qc.checksheet'
    _description = 'QC Check Sheet'
    _order = 'create_date desc'

    name = fields.Char(required=True, default='New Check Sheet')
    header_title = fields.Char(
        string='Check Sheet Header Title',
        help="Printed as the second line of the report's header banner, below the Check Sheet Name.")
    reference = fields.Char(string='Number')
    checksheet_type = fields.Selection(CHECKSHEET_TYPES, required=True, default='standard')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)

    machine_serial = fields.Char(string='Machine Serial')
    check_date = fields.Date(string='Check Date')
    machine_model = fields.Char(string='Model')
    engine_number = fields.Char(string='Engine Number')
    customer = fields.Char(string='Customer')
    job_number = fields.Many2one('project.project', string='Job Number')

    copied_from_id = fields.Many2one('qc.checksheet', string='Copied From', readonly=True, copy=False)

    group_ids = fields.One2many('qc.checksheet.group', 'checksheet_id', string='Inspection Groups')
    panel_line_ids = fields.One2many('qc.checksheet.panel.line', 'checksheet_id', string='Panel Lines')
    approval_ids = fields.One2many('qc.checksheet.approval', 'checksheet_id', string='Approval')
    history_ids = fields.One2many('qc.checksheet.history', 'checksheet_id', string='Template History')
    remarks = fields.Text()

    item_count = fields.Integer(compute='_compute_item_count')

    @api.depends('group_ids.item_ids', 'panel_line_ids')
    def _compute_item_count(self):
        for rec in self:
            if rec.checksheet_type == 'panel_sticker':
                rec.item_count = len(rec.panel_line_ids)
            else:
                rec.item_count = sum(len(g.item_ids) for g in rec.group_ids)

    def action_update_all_panel_images(self):
        """"Update All" button, checksheet-level (techspec §3.4) - only
        meaningful for Panel & Sticker; Standard has no live-linked source to
        refresh from (see techspec §2.1)."""
        for rec in self:
            rec.panel_line_ids.action_update_from_product()

    def _copy_content_from(self, source):
        """Bring over every field from `source` (techspec §3.0, option b):
        general info, Approval, Template History, and Groups/Items or Panel
        Lines. `name`/`reference` are deliberately left untouched - each
        check sheet is its own traceable issued document.
        """
        self.ensure_one()
        if source.checksheet_type != self.checksheet_type:
            raise UserError(_("Can only copy content from a check sheet of the same Type."))

        self.write({
            'header_title': source.header_title,
            'machine_serial': source.machine_serial,
            'check_date': source.check_date,
            'machine_model': source.machine_model,
            'engine_number': source.engine_number,
            'customer': source.customer,
            'job_number': source.job_number.id,
            'remarks': source.remarks,
        })

        for approval in source.approval_ids:
            self.env['qc.checksheet.approval'].create({
                'checksheet_id': self.id,
                'sequence': approval.sequence,
                'position': approval.position,
            })
        for history in source.history_ids:
            self.env['qc.checksheet.history'].create({
                'checksheet_id': self.id,
                'sequence': history.sequence,
                'rev': history.rev,
                'description': history.description,
                'date': history.date,
                'created_by': history.created_by,
                'approved_by': history.approved_by,
            })

        if self.checksheet_type == 'panel_sticker':
            for line in source.panel_line_ids:
                self.env['qc.checksheet.panel.line'].create({
                    'checksheet_id': self.id,
                    'sequence': line.sequence,
                    'part_number': line.part_number.id,
                    'description': line.description,
                    'image': line.image,
                    'qty': line.qty,
                    'note': line.note,
                })
        else:
            for group in source.group_ids:
                self.env['qc.checksheet.group'].create({
                    'checksheet_id': self.id,
                    'sequence': group.sequence,
                    'name': group.name,
                    'item_ids': [
                        (0, 0, {
                            'sequence': item.sequence,
                            'description': item.description,
                            'acceptance': item.acceptance,
                            'note': item.note,
                        }) for item in group.item_ids
                    ],
                })
        self.copied_from_id = source.id
