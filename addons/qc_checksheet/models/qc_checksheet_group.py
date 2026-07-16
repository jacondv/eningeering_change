from odoo import api, fields, models
from odoo.tools import html2plaintext


class QcChecksheetGroup(models.Model):
    """Inspection Group ("Nhóm kiểm tra") - a section title with its own list
    of Items. Item numbering is continuous across the whole check sheet, not
    per group (see QcChecksheetItem.item_number)."""
    _name = 'qc.checksheet.group'
    _description = 'QC Check Sheet Inspection Group'
    _order = 'sequence, id'
    # `name` is Html (needs rich formatting); display_name must stay plain
    # text, so it uses this stripped field instead of `name` directly.
    _rec_name = 'display_title'

    checksheet_id = fields.Many2one('qc.checksheet', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Html(required=True, sanitize_style=True)
    display_title = fields.Char(compute='_compute_display_title', store=True)
    item_ids = fields.One2many('qc.checksheet.item', 'group_id', string='Items')
    item_count = fields.Integer(compute='_compute_item_count')

    @api.depends('name')
    def _compute_display_title(self):
        for rec in self:
            rec.display_title = html2plaintext(rec.name or '')

    @api.depends('item_ids')
    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)


class QcChecksheetItem(models.Model):
    """One inspection question. Only Description/Acceptance/Note are stored -
    Tested and OK/NOK are never entered on the UI, they only ever print as
    blank cells on the PDF (see techspec §2.2)."""
    _name = 'qc.checksheet.item'
    _description = 'QC Check Sheet Item'
    _order = 'sequence, id'

    group_id = fields.Many2one('qc.checksheet.group', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    item_number = fields.Integer(compute='_compute_item_number', store=True)
    description = fields.Html(sanitize_style=True)
    acceptance = fields.Html(sanitize_style=True)
    note = fields.Char()

    @api.depends(
        'sequence',
        'group_id.sequence',
        'group_id.checksheet_id.group_ids.sequence',
        'group_id.checksheet_id.group_ids.item_ids.sequence',
    )
    def _compute_item_number(self):
        for checksheet in self.group_id.checksheet_id:
            counter = 1
            groups = checksheet.group_ids.sorted(lambda g: (g.sequence, g.id))
            for group in groups:
                items = group.item_ids.sorted(lambda i: (i.sequence, i.id))
                for item in items:
                    if item in self:
                        item.item_number = counter
                    counter += 1
        # Items not attached to any checksheet yet (e.g. freshly created in
        # the same transaction, no group committed) still need a value.
        for item in self:
            if not item.group_id.checksheet_id:
                item.item_number = item.sequence
