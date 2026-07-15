from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .qc_checksheet_template import CHECKSHEET_TYPES


class QcChecksheet(models.Model):
    _name = 'qc.checksheet'
    _description = 'QC Check Sheet'
    _order = 'create_date desc'

    name = fields.Char(required=True)
    reference = fields.Char(string='Number')
    checksheet_type = fields.Selection(CHECKSHEET_TYPES, required=True, default='standard')
    template_id = fields.Many2one(
        'qc.checksheet.template', required=True,
        domain="[('checksheet_type', '=', checksheet_type)]")
    company_id = fields.Many2one(related='template_id.company_id', store=True)

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

    @api.onchange('checksheet_type')
    def _onchange_checksheet_type(self):
        if self.template_id and self.template_id.checksheet_type != self.checksheet_type:
            self.template_id = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if 'approval_ids' not in vals and rec.template_id:
                rec._seed_approval_from_template()
        return records

    def _seed_approval_from_template(self):
        """Seed the Approval tab from the Template's default position list.
        Only called at creation time - the Approval tab is free-standing
        afterwards (see techspec §2.1)."""
        self.ensure_one()
        self.approval_ids = [
            (0, 0, {'sequence': line.sequence, 'position': line.position, 'template_position_id': line.id})
            for line in self.template_id.default_approval_position_ids
        ]

    def action_sync_template_branding(self):
        """"Update common info" button (techspec §2.1, feature 1): the
        logo/company name are a live related field already, nothing to copy
        there. What can go stale is the Approval seed list, if the Template's
        default positions were edited/extended after this check sheet was
        created - add any position missing here, without touching or
        removing lines the user already customized.
        """
        for rec in self:
            existing_ids = set(rec.approval_ids.template_position_id.ids)
            missing = rec.template_id.default_approval_position_ids.filtered(
                lambda line: line.id not in existing_ids)
            if missing:
                rec.approval_ids = [
                    (0, 0, {'sequence': line.sequence, 'position': line.position, 'template_position_id': line.id})
                    for line in missing
                ]

    def action_update_all_panel_images(self):
        """"Update All" button, checksheet-level (techspec §3.4) - only
        meaningful for Panel & Sticker; Standard has no live-linked source to
        refresh from (see techspec §2.1)."""
        for rec in self:
            rec.panel_line_ids.action_update_from_product()

    def _copy_content_from(self, source):
        """Bring over Groups/Items or Panel Lines from `source` (techspec
        §3.0, option b). Approval/History are deliberately not copied - they
        are already seeded from the Template and always need a fresh review
        per machine.
        """
        self.ensure_one()
        if source.checksheet_type != self.checksheet_type:
            raise UserError(_("Can only copy content from a check sheet of the same Type."))
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
