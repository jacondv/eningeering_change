import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Where a Model's name can be cut to find the Model it extends: JSV6-EMU-A-068 -> JSV6-EMU-A.
NAME_SEPARATORS = re.compile(r'[-_ /.]')


class QcChecksheetShare(models.Model):
    """A Model that uses another Model's check sheet of a Type instead of having its own: the sheet is
    written and revised once, on the source Model, and the Jobs of both print it. Which Model's sheet a
    Model uses can be changed at any time (names of Models change), and a Model can go back to a sheet of
    its own. A Job keeps the Revision it pinned, whichever way the sheet is reached.

    One level only: a Model that uses another's sheet of a Type is not itself the source of that Type
    for a third."""
    _name = 'qc.checksheet.share'
    _description = 'Check sheet used by another Model'
    _order = 'type_id, model_id'

    model_id = fields.Many2one('equipment.model', string='Model', required=True, index=True, ondelete='cascade')
    type_id = fields.Many2one('qc.checksheet.type', string='Type', required=True, ondelete='cascade')
    source_model_id = fields.Many2one(
        'equipment.model', string='Uses the Sheet Of', required=True, index=True, ondelete='restrict')

    _model_type_unique = models.Constraint(
        'UNIQUE(model_id, type_id)', "This Model already uses another Model's sheet of this Type.")

    @api.constrains('model_id', 'type_id', 'source_model_id')
    def _check_share(self):
        Sheet = self.env['qc.checksheet'].sudo()
        for rec in self:
            if rec.source_model_id == rec.model_id:
                raise UserError(_("A Model can't use its own sheet as another Model's."))
            if Sheet.search_count([('model_id', '=', rec.model_id.id), ('type_id', '=', rec.type_id.id)]):
                raise UserError(_(
                    "%(model)s has a %(type)s sheet of its own. Merge it into the other one, or delete it, first.",
                    model=rec.model_id.display_name, type=rec.type_id.name))
            if not Sheet.search_count([('model_id', '=', rec.source_model_id.id), ('type_id', '=', rec.type_id.id)]):
                raise UserError(_(
                    "%(model)s has no %(type)s sheet to use.",
                    model=rec.source_model_id.display_name, type=rec.type_id.name))
            others = self.sudo().search_count([
                ('type_id', '=', rec.type_id.id), '|',
                ('model_id', '=', rec.source_model_id.id), ('source_model_id', '=', rec.model_id.id)])
            if others:
                raise UserError(_(
                    "A sheet is shared one level only: a Model that uses another's sheet can't be used by a third."))

    # Who owns a sheet

    @api.model
    def _owners(self, models_, types=None):
        """{(model id, type id): source Model} for the Types the given Models use another's sheet of;
        a Type not in it is the Model's own."""
        domain = [('model_id', 'in', models_.ids)]
        if types is not None:
            domain.append(('type_id', 'in', types.ids))
        return {(share.model_id.id, share.type_id.id): share.source_model_id for share in self.sudo().search(domain)}

    @api.model
    def _owner(self, model, checksheet_type):
        """The Model whose sheet of this Type `model` prints: its source, or itself."""
        share = self.sudo().search([('model_id', '=', model.id), ('type_id', '=', checksheet_type.id)], limit=1)
        return share.source_model_id or model

    @api.model
    def _users_of(self, model, checksheet_type=None):
        """The shares that use `model`'s sheet (of one Type, or all)."""
        domain = [('source_model_id', '=', model.id)]
        if checksheet_type:
            domain.append(('type_id', '=', checksheet_type.id))
        return self.sudo().search(domain)

    @api.model
    def _ready_types(self, models_, types):
        """{model id: ids of the Types among `types` the Model has a Released sheet of}, its own or its source's."""
        owners = self._owners(models_, types)
        sources = self.env['equipment.model'].sudo().union(*owners.values()) if owners else models_.browse()
        released = self.env['qc.checksheet'].sudo()._read_group(
            [('model_id', 'in', (models_ | sources).ids), ('state', '=', 'released'), ('type_id', 'in', types.ids)],
            ['model_id'], ['type_id:array_agg'])
        released_by_model = {model.id: set(type_ids) for model, type_ids in released}
        return {
            model.id: {
                type_id for type_id in types.ids
                if type_id in released_by_model.get(
                    owners.get((model.id, type_id), model).id, set())
            } for model in models_
        }

    @api.model
    def _suggest_source(self, model, checksheet_type):
        """The Model most likely meant as the source: the longest of its name's beginnings (cut at - _ / . or a
        space) that is a Model with a sheet of this Type to use. JSV6-EMU-A-068 -> JSV6-EMU-A."""
        name = model.name or ''
        prefixes = {name[:match.start()] for match in NAME_SEPARATORS.finditer(name) if match.start()}
        if not prefixes:
            return self.env['equipment.model']
        candidates = self.env['equipment.model'].sudo().with_context(active_test=False).search([
            ('name', 'in', list(prefixes)), ('id', '!=', model.id)])
        with_sheet = self.env['qc.checksheet'].sudo()._read_group(
            [('model_id', 'in', candidates.ids), ('type_id', '=', checksheet_type.id)], ['model_id'])
        usable = candidates.filtered(lambda candidate: candidate in {group[0] for group in with_sheet})
        # A source that itself uses another's sheet of this Type can't be used (one level only).
        chained = self.sudo().search([('type_id', '=', checksheet_type.id), ('model_id', 'in', usable.ids)]).model_id
        usable -= chained
        return usable.sorted(lambda candidate: -len(candidate.name))[:1]
