import logging
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_LENGTH_TOLERANCE = 100.0
PART_NUMBER_MODEL = 'part_number_manager.part_number'


class JobHoseLine(models.Model):
    """One hose assembly needed for a Job - one row on the Hose & Fitting
    Builder page. Reuses an existing "Hose and Fitting" Part Number when
    one with the same BOM (Hose + Fitting1 + Fitting2 + whichever
    Ferrules/Fire Wrap/Hose Guard actually apply) and a Length within that
    Part's own tolerance already exists; otherwise a new one is generated
    with a fresh BOM.
    """
    _name = 'hose_fitting_manager.job_hose_line'
    _description = 'Job Hose And Fitting Line'
    _order = 'job_number, sequence, id'

    job_number = fields.Many2one('project.project', string='Job Number', required=True, index=True)
    sequence = fields.Integer(default=10)
    config_id = fields.Many2one('hose_fitting_manager.config', string='Hose Symbol')
    hose_number = fields.Char(string='Hose Number')
    function_id = fields.Many2one(
        'hose_fitting_manager.function', string='Function',
        help="Picked from the shared Function list (Configuration > Functions) - not tied to "
             "Symbol/Config, and not a Part Number.")
    description_en = fields.Char(string='Description (EN)')
    description_vn = fields.Char(string='Description (VN)')
    quantity = fields.Integer(default=1, required=True)

    hose_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Hose', required=True, domain="[('part_type_id.name', '=', 'Hose')]")
    length = fields.Float(required=True)

    fitting1_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Fitting 1', required=True, domain="[('part_type_id.name', '=', 'Fitting')]")
    ferrule1_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Ferrule (Fitting 1)', domain="[('part_type_id.name', '=', 'Ferrule')]")
    fitting2_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Fitting 2', required=True, domain="[('part_type_id.name', '=', 'Fitting')]")
    ferrule2_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Ferrule (Fitting 2)', domain="[('part_type_id.name', '=', 'Ferrule')]")

    fire_wrap_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Fire Wrap', domain="[('part_type_id.name', '=', 'Fire Wrap')]",
        help="Optional - left blank means no Fire Wrap on this line.")
    hose_guard_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Hose Guard', domain="[('part_type_id.name', '=', 'Hose Guard')]",
        help="Optional - left blank means no Hose Guard on this line.")

    part_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Hose and Fitting Part', required=True,
        help="The assembly Part Number this line resolved to - either reused from an existing "
             "match, or newly generated for this exact BOM + Length.")

    # Set only via the Wire wizard (action_open_wire_wizard below), never
    # hand-edited - see JobEquipmentItem.get_open_port_ids for how a
    # Port's used/open state is derived from these two pairs.
    from_item_id = fields.Many2one(
        'hose_fitting_manager.job_equipment_item', string='From Item',
        domain="[('job_number', '=', job_number)]")
    from_port_id = fields.Many2one(
        'part_number_manager.part_attribute_value', string='From Port')
    to_item_id = fields.Many2one(
        'hose_fitting_manager.job_equipment_item', string='To Item',
        domain="[('job_number', '=', job_number)]")
    to_port_id = fields.Many2one(
        'part_number_manager.part_attribute_value', string='To Port')

    def action_open_wire_wizard(self):
        self.ensure_one()
        wizard = self.env['hose_fitting_manager.wire_wizard'].create({
            'line_id': self.id,
            'job_number': self.job_number.id,
            'from_item_id': self.from_item_id.id,
            'from_port_id': self.from_port_id.id,
            'to_item_id': self.to_item_id.id,
            'to_port_id': self.to_port_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hose_fitting_manager.wire_wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def _report_part_description(self, part):
        """Display text for a component Part on the report (Fitting 1/2,
        Hose Guard) - same fallback order used throughout the app (Builder
        page, list views): Display Description, then Short Description,
        never the raw Part Number code. Blank (not "(No description)") when
        the Part itself is unset, e.g. an optional Hose Guard left blank.
        """
        if not part:
            return ''
        return part.display_description or part.short_description or ''

    @api.model
    def find_matches(self, component_ids, length=None, tolerance=None):
        """Existing assembled Hose and Fitting Parts whose BOM is *exactly*
        `component_ids` (as a multiset - order-independent, duplicates
        matter, e.g. the same Ferrule used on both Fittings) and no other
        component. With `length` omitted, returns *every* such Part
        (regardless of Length) - used to fill the Length field's dropdown
        the moment it's focused, before anything is typed. With `length`
        given, filtered to `abs(part.length - length) <= tolerance` - the
        tolerance the user is currently entering on the Builder page, not
        each candidate's own stored `length_tolerance` (that field only
        records what tolerance was in effect when a given assembly was
        generated - see create_batch). Returns [{id, part_number, length}].
        """
        component_ids = [c for c in component_ids if c]
        if not component_ids:
            return []
        wanted = Counter(component_ids)
        bom_line_model = self.env['hose_fitting_manager.bom_line']
        bom_lines = bom_line_model.search([('component_part_id', 'in', list(wanted))])
        components_by_parent = {}
        for line in bom_lines:
            components_by_parent.setdefault(line.parent_part_id, []).append(line.component_part_id.id)

        matches = []
        for part, ids in components_by_parent.items():
            if Counter(ids) != wanted:
                continue
            total_lines = bom_line_model.search_count([('parent_part_id', '=', part.id)])
            if total_lines != len(ids):
                continue
            if length is not None and abs(part.length - length) > (tolerance if tolerance is not None else DEFAULT_LENGTH_TOLERANCE):
                continue
            matches.append({'id': part.id, 'part_number': part.part_number, 'length': part.length})
        return matches


    # Fields that make up an assembly's BOM - changing any of them (or the
    # Length) on a saved line means its Part Number may no longer fit.
    COMPONENT_FIELDS = ('hose_id', 'fitting1_id', 'ferrule1_id', 'fitting2_id', 'ferrule2_id',
                        'fire_wrap_id', 'hose_guard_id')
    # Everything update_line lets the Builder's Job Lines table change.
    EDITABLE_FIELDS = COMPONENT_FIELDS + ('length', 'config_id', 'hose_number', 'function_id',
                                          'description_en', 'description_vn', 'quantity')

    @api.model
    def _create_assembly_part(self, vals, material_group_id, length_tolerance=None):
        """New "Hose And Fitting" Part Number + its BOM for the components
        and Length in `vals` - shared by create_batch and update_line,
        whenever no existing assembly fits."""
        if not material_group_id:
            raise UserError(_('Material Group is required to generate a new Hose and Fitting Part Number.'))
        part_model = self.env[PART_NUMBER_MODEL]
        # Case-insensitive - the actual record is named "Hose And Fitting"
        # (capital A); matching case-sensitively previously found nothing,
        # silently leaving every generated assembly Part with no Part Type.
        part_type = self.env['part_number_manager.part_type'].search(
            [('name', '=ilike', 'Hose and Fitting')], limit=1)
        if not part_type:
            raise UserError(_('Part Type "Hose And Fitting" was not found - check Part Types.'))
        length = vals['length']
        suffix = part_model._get_next_suffix(material_group_id)
        group = self.env['part_number_manager.material_group'].browse(material_group_id)
        # "1.2m - 1/2" x 6SN (8EFG6K) Hose Assy" - Length in meters (mm
        # stored / 1000, trailing zeros trimmed) + the Hose component's own
        # description, same fallback order as _report_part_description.
        hose = part_model.browse(vals['hose_id'])
        hose_desc = hose.display_description or hose.short_description or ''
        new_part = part_model.with_context(skip_job_number_check=True).create({
            'material_group_id': material_group_id,
            'sequence_suffix': suffix,
            'part_number': f'{group.code}{suffix}',
            'part_type_id': part_type.id,
            'make_buy': 'make',
            'length': length,
            'length_tolerance': length_tolerance or DEFAULT_LENGTH_TOLERANCE,
            'short_description': f'{length / 1000.0:g}m - {hose_desc} Hose Assy'.strip(),
        })
        roles = [('hose_id', 'hose', 10), ('fitting1_id', 'fitting', 20), ('fitting2_id', 'fitting', 30),
                 ('ferrule1_id', 'ferrule', 40), ('ferrule2_id', 'ferrule', 50),
                 ('fire_wrap_id', 'fire_wrap', 60), ('hose_guard_id', 'hose_guard', 70)]
        self.env['hose_fitting_manager.bom_line'].create([
            {'parent_part_id': new_part.id, 'component_part_id': vals[field], 'role': role, 'sequence': seq}
            for field, role, seq in roles if vals.get(field)
        ])
        return new_part

    def _part_fits(self, part, component_ids, length):
        """Whether `part`'s BOM is exactly `component_ids` (as a multiset)
        and its Length is exactly `length`."""
        if not part:
            return False
        bom = self.env['hose_fitting_manager.bom_line'].search([('parent_part_id', '=', part.id)])
        return (Counter(bom.mapped('component_part_id').ids) == Counter(component_ids)
                and abs(part.length - length) < 1e-6)

    def update_line(self, vals, part_id=False, material_group_id=False, length_tolerance=None,
                    confirm_new_part=False):
        """Saves an edit made in the Builder's Job Lines table.

        Changing only Function/Hose Number/Descriptions/Quantity keeps the
        line's Part Number. Changing a component or the Length re-resolves
        it: the current Part if it still fits, else `part_id` (the user's
        pick from the Length dropdown) if it fits, else any existing Part
        with exactly this BOM and Length, else a brand new one - created
        only once the user has confirmed it (`confirm_new_part`), since it
        adds a Part Number to the Material Group. The old Part is never
        touched - other lines/Jobs may still use it.

        Returns {'status': 'saved', 'part_number': ...},
        {'status': 'needs_material_group'} or {'status': 'needs_confirmation'}.
        """
        self.ensure_one()
        vals = {key: value for key, value in vals.items() if key in self.EDITABLE_FIELDS}
        merged = {field: vals.get(field, self[field].id) or False for field in self.COMPONENT_FIELDS}
        merged['length'] = vals.get('length', self.length)
        if not (merged['hose_id'] and merged['fitting1_id'] and merged['fitting2_id']):
            raise UserError(_('Hose and both Fittings are required.'))

        changed = (any(merged[field] != (self[field].id or False) for field in self.COMPONENT_FIELDS)
                   or abs(merged['length'] - self.length) >= 1e-6)
        part = self.part_id
        if changed:
            component_ids = [merged[field] for field in self.COMPONENT_FIELDS if merged[field]]
            part_model = self.env[PART_NUMBER_MODEL]
            part = next((candidate for candidate in (self.part_id, part_model.browse(part_id or []))
                         if self._part_fits(candidate, component_ids, merged['length'])), None)
            if not part:
                match = self.find_matches(component_ids, merged['length'], tolerance=0)
                part = part_model.browse(match[0]['id']) if match else None
            if not part:
                if not material_group_id:
                    return {'status': 'needs_material_group'}
                if not confirm_new_part:
                    return {'status': 'needs_confirmation'}
                part = self._create_assembly_part(merged, material_group_id, length_tolerance)

        self.write(dict(vals, part_id=part.id))
        return {'status': 'saved', 'part_number': part.part_number}

    @api.model
    def create_batch(self, vals_list):
        """Single entry point the OWL Builder page calls on Save (Manual
        Lines) and on the Port Board's per-line create. Each row runs in its
        own savepoint, same partial-success pattern as part_number_manager's
        own create_batch_with_generated_number. `part_id` already set means
        the row matched an existing assembly to reuse; unset means a brand
        new one is generated (requiring `material_group_id`, a transient
        input not stored on this model - Material Group belongs to the
        assembly Part Number, not the line).
        """
        results = []
        for idx, vals in enumerate(vals_list):
            result = {'index': idx, 'success': False, 'id': None, 'part_number': None, 'error': None}
            try:
                with self.env.cr.savepoint():
                    vals = dict(vals)
                    part_id = vals.pop('part_id', None)
                    material_group_id = vals.pop('material_group_id', None)
                    length_tolerance = vals.pop('length_tolerance', None)

                    if not (vals.get('hose_id') and vals.get('fitting1_id') and vals.get('fitting2_id')):
                        raise UserError(_('Hose and both Fittings are required.'))
                    if not vals.get('job_number'):
                        raise UserError(_('Job Number is required.'))

                    if not part_id:
                        part_id = self._create_assembly_part(vals, material_group_id, length_tolerance).id

                    vals['part_id'] = part_id
                    line = self.create(vals)
                    result['success'] = True
                    result['id'] = line.id
                    result['part_number'] = line.part_id.part_number

            except Exception as exc:
                result['error'] = str(exc)
                _logger.warning('Job Hose Line creation failed for row %s: %s', idx, exc)

            results.append(result)

        return results
