from odoo import api, fields, models
from odoo.exceptions import UserError


class InventorBomType(models.Model):
    """Registry mapping a `bom_type` key (e.g. "panel_sticker") to the Odoo
    technical model name that stores that type's lines. A business module
    that owns a BOM type declares one record here via XML data - this
    connector never needs to know what fields that line model has, only
    that it exposes a `bom_id` Many2one back to `inventor.bom`.
    """
    _name = 'inventor.bom.type'
    _description = 'Inventor BOM Type Registry'

    code = fields.Char(required=True, help="Key sent by Inventor as 'bom_type' in the payload.")
    name = fields.Char(required=True)
    line_model = fields.Char(
        required=True,
        help="Technical name of the model that stores this BOM type's lines "
             "(must have a 'bom_id' Many2one to inventor.bom, ondelete='cascade').")

    _code_unique = models.Constraint(
        'unique(code)', 'A BOM type with this code is already registered.')


class InventorBom(models.Model):
    """One header per (model, bom_type) pushed from Inventor. Lines are NOT
    a fixed One2many here - each bom_type stores its lines in whichever
    model `inventor.bom.type` registers for it, since different BOM types
    need different columns (see techspec).
    """
    _name = 'inventor.bom'
    _description = 'Inventor BOM'
    _order = 'model, bom_type'

    model = fields.Char(required=True, string='Machine Model')
    bom_type = fields.Selection(selection='_selection_bom_type', required=True)
    name = fields.Char()
    last_synced = fields.Datetime()

    _model_bom_type_unique = models.Constraint(
        'unique(model, bom_type)', 'A BOM for this Model and Type already exists.')

    @api.model
    def _selection_bom_type(self):
        return [(t.code, t.name) for t in self.env['inventor.bom.type'].search([])]

    def _compute_display_name(self):
        for rec in self:
            label = "%s - %s" % (rec.model, rec.bom_type)
            if rec.name:
                label += " (%s)" % rec.name
            rec.display_name = label

    @api.model
    def _upsert_from_payload(self, payload):
        """Create/update the header and fully replace its lines from a
        parsed REST payload: {model, bom_type, name (optional), lines: [...]}.

        Raises UserError on anything the controller should turn into a 400 -
        this method never touches HTTP concerns.
        """
        model = payload.get('model')
        bom_type = payload.get('bom_type')
        lines = payload.get('lines')
        if not model or not bom_type:
            raise UserError("Payload must include both 'model' and 'bom_type'.")
        if not isinstance(lines, list):
            raise UserError("Payload must include a 'lines' array.")

        bom_type_record = self.env['inventor.bom.type'].search([('code', '=', bom_type)], limit=1)
        if not bom_type_record:
            raise UserError("Unknown bom_type: %s" % bom_type)

        line_model = bom_type_record.line_model
        if line_model not in self.env:
            raise UserError("bom_type %s is registered to an unknown model: %s" % (bom_type, line_model))

        bom = self.search([('model', '=', model), ('bom_type', '=', bom_type)], limit=1)
        values = {
            'model': model,
            'bom_type': bom_type,
            'name': payload.get('name'),
            'last_synced': fields.Datetime.now(),
        }
        if bom:
            bom.write(values)
        else:
            bom = self.create(values)

        LineModel = self.env[line_model]
        LineModel.search([('bom_id', '=', bom.id)]).unlink()
        for line in lines:
            LineModel.create({**line, 'bom_id': bom.id})

        return bom
