from odoo import _, api, fields, models
from odoo.exceptions import UserError

PART_ATTRIBUTE_VALUE_MODEL = 'part_number_manager.part_attribute_value'


class HoseFittingWireWizard(models.TransientModel):
    """"Wire" popup - picks which Port of which Job Equipment Item this
    Hose connects From, and which it connects To, then (re)generates the
    Description EN/VN for that connection. Confirming always overwrites
    the existing Description, even a hand-edited one - Wire is the source
    of truth for what a line's Description says once used at all.

    Works in two modes, both ending up with the same From/To/Description
    on `description_preview`:
    - `line_id` set (opened from an already-saved Job Hose Line, e.g. the
      "Wire" button on All Lines or on a saved row of the Create List
      page's Job Lines table): action_confirm also writes the result onto
      that line directly.
    - `line_id` empty (opened from a still-unsaved row while building a
      list on the Create List page - see builder.js's openRowWireWizard):
      there's no line yet to write onto, so action_confirm only validates;
      the caller reads this wizard's own fields back after it closes and
      carries them into the row, to be sent along on the eventual Save.
    """
    _name = 'hose_fitting_manager.wire_wizard'
    _description = 'Wire Hose Connection'

    line_id = fields.Many2one('hose_fitting_manager.job_hose_line', ondelete='cascade')
    # Not related to line_id - a still-unsaved Create List row has no line
    # to relate through, so the caller always sets this explicitly on
    # create (see JobHoseLine.action_open_wire_wizard and builder.js).
    job_number = fields.Many2one('project.project', string='Job Number')

    # Not required=True at the field level on purpose - the wizard is
    # first created blank (the usual "not Wired yet" case) and only needs
    # to be complete by the time action_confirm runs, which checks
    # explicitly below. The form view still marks these required="1" so
    # the UI itself won't let you submit a blank one.
    from_item_id = fields.Many2one(
        'hose_fitting_manager.job_equipment_item', string='From Item',
        domain="[('job_number', '=', job_number)]")
    from_available_port_ids = fields.Many2many(
        PART_ATTRIBUTE_VALUE_MODEL, 'hfm_wire_wizard_from_port_rel', compute='_compute_available_ports')
    from_port_id = fields.Many2one(
        PART_ATTRIBUTE_VALUE_MODEL, string='From Port',
        domain="[('id', 'in', from_available_port_ids)]")

    to_item_id = fields.Many2one(
        'hose_fitting_manager.job_equipment_item', string='To Item',
        domain="[('job_number', '=', job_number)]")
    to_available_port_ids = fields.Many2many(
        PART_ATTRIBUTE_VALUE_MODEL, 'hfm_wire_wizard_to_port_rel', compute='_compute_available_ports')
    to_port_id = fields.Many2one(
        PART_ATTRIBUTE_VALUE_MODEL, string='To Port',
        domain="[('id', 'in', to_available_port_ids)]")

    # Ports to additionally treat as taken, on top of whatever's already
    # Wired in the database - the Create List page passes in the Ports
    # already picked on *other* still-unsaved rows in the same batch here,
    # since those wouldn't otherwise show as used yet (see builder.js).
    exclude_port_ids = fields.Many2many(
        PART_ATTRIBUTE_VALUE_MODEL, 'hfm_wire_wizard_exclude_port_rel', string='Exclude Ports')

    description_preview_en = fields.Char(compute='_compute_description_preview')
    description_preview_vn = fields.Char(compute='_compute_description_preview')

    @api.depends('from_item_id', 'to_item_id', 'line_id', 'exclude_port_ids')
    def _compute_available_ports(self):
        value_model = self.env[PART_ATTRIBUTE_VALUE_MODEL]
        for rec in self:
            from_open = value_model.browse(
                rec.from_item_id.get_open_port_ids(exclude_line=rec.line_id) if rec.from_item_id else [])
            to_open = value_model.browse(
                rec.to_item_id.get_open_port_ids(exclude_line=rec.line_id) if rec.to_item_id else [])
            rec.from_available_port_ids = from_open - rec.exclude_port_ids
            rec.to_available_port_ids = to_open - rec.exclude_port_ids

    @api.depends('from_item_id', 'from_port_id', 'to_item_id', 'to_port_id')
    def _compute_description_preview(self):
        for rec in self:
            if rec.from_item_id and rec.from_port_id and rec.to_item_id and rec.to_port_id:
                # display_value, not value_char directly - reads correctly
                # whether Port ends up a Selection or a Char attribute (see
                # part_attribute_value._compute_display_value). EN uses each
                # Item's description_en, VN uses description_vn - never
                # cross-mixed (that used to be the same text for both).
                rec.description_preview_en = '%s (%s) → %s (%s)' % (
                    rec.from_item_id.description_en, rec.from_port_id.display_value,
                    rec.to_item_id.description_en, rec.to_port_id.display_value)
                rec.description_preview_vn = '%s (%s) → %s (%s)' % (
                    rec.from_item_id.description_vn, rec.from_port_id.display_value,
                    rec.to_item_id.description_vn, rec.to_port_id.display_value)
            else:
                rec.description_preview_en = False
                rec.description_preview_vn = False

    @api.onchange('from_item_id')
    def _onchange_from_item_id(self):
        self.from_port_id = False

    @api.onchange('to_item_id')
    def _onchange_to_item_id(self):
        self.to_port_id = False

    def action_confirm(self):
        self.ensure_one()
        if not (self.from_item_id and self.from_port_id and self.to_item_id and self.to_port_id):
            raise UserError(_('Pick both a From and a To Item/Port before confirming.'))
        if self.from_item_id == self.to_item_id and self.from_port_id == self.to_port_id:
            raise UserError(_('From and To must be different Ports.'))
        if self.line_id:
            self.line_id.write({
                'from_item_id': self.from_item_id.id,
                'from_port_id': self.from_port_id.id,
                'to_item_id': self.to_item_id.id,
                'to_port_id': self.to_port_id.id,
                'description_en': self.description_preview_en,
                'description_vn': self.description_preview_vn,
            })
        # No line_id: nothing to write onto yet - the caller (builder.js)
        # reads description_preview_en/vn and the From/To picks straight off
        # this wizard record after the dialog closes.
        return {'type': 'ir.actions.act_window_close'}
