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
    Ferrules/Fire Wrap actually apply) and a Length within that Part's own
    tolerance already exists; otherwise a new one is generated with a
    fresh BOM.
    """
    _name = 'hose_fitting_manager.job_hose_line'
    _description = 'Job Hose And Fitting Line'
    _order = 'job_number, sequence, id'

    job_number = fields.Many2one('project.project', string='Job Number', required=True, index=True)
    sequence = fields.Integer(default=10)
    config_id = fields.Many2one('hose_fitting_manager.config', string='Hose Symbol')
    hose_number = fields.Char(string='Hose Number')
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

    part_id = fields.Many2one(
        PART_NUMBER_MODEL, string='Hose and Fitting Part', required=True,
        help="The assembly Part Number this line resolved to - either reused from an existing "
             "match, or newly generated for this exact BOM + Length.")

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

    @api.model
    def create_batch(self, vals_list):
        """Single entry point the OWL Builder page calls on Save. Each row
        runs in its own savepoint, same partial-success pattern as
        part_number_manager's own create_batch_with_generated_number.
        `part_id` already set means the row matched an existing assembly to
        reuse; unset means a brand new one is generated (requiring
        `material_group_id`, a transient input not stored on this model -
        Material Group belongs to the assembly Part Number, not the line).
        """
        part_model = self.env[PART_NUMBER_MODEL]
        bom_line_model = self.env['hose_fitting_manager.bom_line']
        results = []
        for idx, vals in enumerate(vals_list):
            result = {'index': idx, 'success': False, 'id': None, 'part_number': None, 'error': None}
            try:
                with self.env.cr.savepoint():
                    vals = dict(vals)
                    part_id = vals.pop('part_id', None)
                    material_group_id = vals.pop('material_group_id', None)
                    length_tolerance = vals.pop('length_tolerance', None)
                    hose_id = vals.get('hose_id')
                    fitting1_id = vals.get('fitting1_id')
                    fitting2_id = vals.get('fitting2_id')
                    ferrule1_id = vals.get('ferrule1_id')
                    ferrule2_id = vals.get('ferrule2_id')
                    fire_wrap_id = vals.get('fire_wrap_id')
                    length = vals.get('length')

                    if not (hose_id and fitting1_id and fitting2_id):
                        raise UserError(_('Hose and both Fittings are required.'))
                    if not vals.get('job_number'):
                        raise UserError(_('Job Number is required.'))

                    if not part_id:
                        if not material_group_id:
                            raise UserError(_(
                                'Material Group is required to generate a new Hose and Fitting Part Number.'))
                        # Case-insensitive - the actual record is named
                        # "Hose And Fitting" (capital A); matching case-
                        # sensitively here previously found nothing, silently
                        # leaving every generated assembly Part with no
                        # Part Type at all.
                        part_type = self.env['part_number_manager.part_type'].search(
                            [('name', '=ilike', 'Hose and Fitting')], limit=1)
                        if not part_type:
                            raise UserError(_('Part Type "Hose And Fitting" was not found - check Part Types.'))
                        suffix = part_model._get_next_suffix(material_group_id)
                        group = self.env['part_number_manager.material_group'].browse(material_group_id)
                        new_part = part_model.with_context(skip_job_number_check=True).create({
                            'material_group_id': material_group_id,
                            'sequence_suffix': suffix,
                            'part_number': f'{group.code}{suffix}',
                            'part_type_id': part_type.id,
                            'make_buy': 'make',
                            'length': length,
                            'length_tolerance': length_tolerance or DEFAULT_LENGTH_TOLERANCE,
                        })
                        lines = [
                            {'parent_part_id': new_part.id, 'component_part_id': hose_id,
                             'role': 'hose', 'sequence': 10},
                            {'parent_part_id': new_part.id, 'component_part_id': fitting1_id,
                             'role': 'fitting', 'sequence': 20},
                            {'parent_part_id': new_part.id, 'component_part_id': fitting2_id,
                             'role': 'fitting', 'sequence': 30},
                        ]
                        if ferrule1_id:
                            lines.append({'parent_part_id': new_part.id, 'component_part_id': ferrule1_id,
                                           'role': 'ferrule', 'sequence': 40})
                        if ferrule2_id:
                            lines.append({'parent_part_id': new_part.id, 'component_part_id': ferrule2_id,
                                           'role': 'ferrule', 'sequence': 50})
                        if fire_wrap_id:
                            lines.append({'parent_part_id': new_part.id, 'component_part_id': fire_wrap_id,
                                           'role': 'fire_wrap', 'sequence': 60})
                        bom_line_model.create(lines)
                        part_id = new_part.id

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
