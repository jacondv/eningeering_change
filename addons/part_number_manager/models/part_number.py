import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

SUFFIX_RANGE = 10000


class PartNumber(models.Model):
    """Company part number, kept independent from `product.product`:
    business `state` (draft/active/obsolete) is not Odoo's `active`
    boolean, and most parts never need product.product's commercial
    fields (see techspec 2.1).

    `part_number` is never typed by hand - it is always
    `material_group_id.code` + a gap-filling 4-digit suffix, assigned by
    `create_batch_with_generated_number` (see 5.1/5.2 below).
    """
    _name = 'part_number_manager.part_number'
    _description = 'Part Number'
    _inherit = ['mail.thread']
    _order = 'part_number'
    _rec_name = 'part_number'

    part_number = fields.Char(
        index=True, copy=False, readonly=True,
        help="Generated via the Generate button (material_group.code + sequence_suffix). Never entered by hand.")
    sequence_suffix = fields.Char(size=4, copy=False, readonly=True)
    material_group_id = fields.Many2one(
        'part_number_manager.material_group', string='Material Group', required=True, index=True)
    job_number = fields.Many2one('project.project', string='Job Number')
    short_description = fields.Char()
    long_description = fields.Text()
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('obsolete', 'Obsolete'),
    ], default='draft', tracking=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    vendor_ref = fields.Char(string='Vendor Reference')
    part_type_id = fields.Many2one(
        'part_number_manager.part_type', string='Part Type',
        help="Set only when this part is built from a BOM.")

    attribute_value_ids = fields.One2many(
        'part_number_manager.part_attribute_value', 'part_id', string='Attribute Values')
    superseded_ids = fields.One2many(
        'part_number_manager.part_number_mapping', 'new_part_id', string='Legacy Codes Replaced')
    supersedes_ids = fields.One2many(
        'part_number_manager.part_number_mapping', 'legacy_part_id', string='Replaced By')
    replacement_display = fields.Char(
        compute='_compute_replacement_display', store=True,
        help="Comma-separated part numbers superseding this (legacy) part - shown on list/search views.")
    legacy_codes_display = fields.Char(
        compute='_compute_legacy_codes_display', store=True,
        help="Comma-separated legacy part numbers this part replaces - shown on list/search views.")
    attribute_display = fields.Char(
        compute='_compute_attribute_display', store=True,
        help="Comma-separated 'Attribute: Value' pairs - shown on list/search views.")

    _part_number_unique = models.Constraint(
        'unique(part_number)',
        'This Part Number already exists. The advisory lock in _get_next_suffix should have prevented this.')

    @api.depends('supersedes_ids.new_part_id.part_number')
    def _compute_replacement_display(self):
        for rec in self:
            rec.replacement_display = ', '.join(rec.supersedes_ids.mapped('new_part_id.part_number'))

    @api.depends('superseded_ids.legacy_part_id.part_number')
    def _compute_legacy_codes_display(self):
        for rec in self:
            rec.legacy_codes_display = ', '.join(rec.superseded_ids.mapped('legacy_part_id.part_number'))

    @api.depends('attribute_value_ids.attribute_id.name', 'attribute_value_ids.display_value')
    def _compute_attribute_display(self):
        for rec in self:
            rec.attribute_display = ', '.join(
                f'{value.attribute_id.name}: {value.display_value}'
                for value in rec.attribute_value_ids if value.display_value)

    @api.constrains('state', 'part_number')
    def _check_active_requires_part_number(self):
        for rec in self:
            if rec.state == 'active' and not rec.part_number:
                raise ValidationError(_('This part has no Part Number yet - Generate one before setting it Active.'))

    @api.constrains('part_number', 'material_group_id', 'sequence_suffix')
    def _check_part_number_format(self):
        # Warn only: a part_number can legitimately drift from
        # material_group.code + sequence_suffix if someone edited the DB
        # directly. That is rare and not worth blocking the record for
        # (see techspec 2.4).
        for rec in self:
            if not rec.part_number:
                continue
            expected = f'{rec.material_group_id.code}{rec.sequence_suffix}'
            if rec.part_number != expected:
                _logger.warning(
                    "Part Number %s (id=%s) does not match material_group.code + "
                    "sequence_suffix (expected %s).", rec.part_number, rec.id, expected)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('skip_job_number_check'):
            for vals in vals_list:
                if not vals.get('job_number'):
                    raise UserError(_('Job Number is required when creating a part.'))
        return super().create(vals_list)

    @api.model
    def _get_next_suffix(self, material_group_id):
        """Real suffix, used on Save. Takes a Postgres advisory transaction
        lock keyed on material_group_id so two transactions creating a part
        in the same group at the same time can't compute the same suffix
        (see techspec 2.4/5.1).
        """
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', (material_group_id,))
        return self._compute_next_suffix(material_group_id)

    @api.model
    def preview_next_suffix(self, material_group_id):
        """Read-only preview for the Generate button: no lock, no write.
        May differ from the real suffix assigned on Save if someone else
        creates a part in the same group in between - that is expected and
        acceptable (see techspec 2.4/5.1).
        """
        if not material_group_id:
            return False
        return self._compute_next_suffix(material_group_id)

    @api.model
    def _compute_next_suffix(self, material_group_id):
        existing = self.search([
            ('material_group_id', '=', material_group_id),
        ]).mapped('sequence_suffix')
        used = {int(s) for s in existing if s}
        for i in range(SUFFIX_RANGE):
            if i not in used:
                return f'{i:04d}'
        raise UserError(_('This Material Group has used up all 10,000 available codes (0000-9999).'))

    def _create_attribute_value(self, part, attribute_id, value):
        """Routes an incoming (attribute_id, value) pair from the OWL page
        into whichever column `attribute_id.value_type` actually uses -
        `value_float`/`value_option_id`/`value_char` - never blindly into
        `value_char` regardless of type, or the wrong column stays empty and
        `display_value` silently shows a bogus default (e.g. "0.0 mm" for a
        Number attribute whose value never made it into value_float).
        """
        attribute = self.env['part_number_manager.part_attribute'].browse(attribute_id)
        vals = {'part_id': part.id, 'attribute_id': attribute.id}
        if attribute.value_type == 'float':
            try:
                vals['value_float'] = float(value)
            except (TypeError, ValueError):
                raise UserError(_('"%(value)s" is not a valid number for attribute "%(attribute)s".') % {
                    'value': value, 'attribute': attribute.name,
                })
        elif attribute.value_type == 'selection':
            option = self.env['part_number_manager.part_attribute_option'].search([
                ('attribute_id', '=', attribute.id), ('name', '=', value),
            ], limit=1)
            if not option:
                raise UserError(_('"%(value)s" is not a valid option for attribute "%(attribute)s".') % {
                    'value': value, 'attribute': attribute.name,
                })
            vals['value_option_id'] = option.id
        else:
            vals['value_char'] = value
        self.env['part_number_manager.part_attribute_value'].create(vals)

    @api.model
    def create_batch_with_generated_number(self, vals_list):
        """Single entry point OWL calls on Save, for both the "Create New"
        and "Convert Legacy Code" flows (distinguished per-row by the
        presence of `conversion_legacy_id`/`conversion_legacy_text`). Each
        row runs in its own savepoint: a failing row (e.g. a rare
        part_number collision) is rolled back on its own, without affecting
        rows that already succeeded in the same batch (see techspec 5.2).

        On conversions, the target Part Number is resolved as:
        - `existing_new_part_id` set -> attach the legacy code to that
          existing part, no new part created. This is the only way a
          legacy code may be converted more than once (true N-N mapping).
        - both `existing_new_part_id` and `target_part_text` empty -> a new
          Part Number is generated, same as the "Create New" flow - but
          only if this legacy code has never been converted before
          (state != 'obsolete'); auto-generating a second new Part Number
          for an already-converted legacy code is rejected, it must be
          done by explicitly picking an existing Part Number instead.
        - `target_part_text` set but `existing_new_part_id` empty -> the
          user typed something that didn't match any existing Part Number;
          this is an error, never silently falls back to generating a new
          one (a typo must not create an unrelated new part).
        Only the *legacy* side may be created on the fly, via
        `conversion_legacy_text` when the autocomplete had no match. Job
        Number is only mandatory for rows that create a brand new part
        outside of a conversion.
        """
        results = []
        for idx, vals in enumerate(vals_list):
            result = {'index': idx, 'success': False, 'part_id': None, 'error': None, 'part_number': None}
            try:
                with self.env.cr.savepoint():
                    vals = dict(vals)
                    attribute_values = vals.pop('attribute_values', [])
                    conversion_legacy_id = vals.pop('conversion_legacy_id', None)
                    conversion_legacy_text = vals.pop('conversion_legacy_text', None)
                    existing_new_part_id = vals.pop('existing_new_part_id', None)
                    target_part_text = vals.pop('target_part_text', None)
                    is_conversion = bool(conversion_legacy_id or conversion_legacy_text)

                    if not vals.get('material_group_id'):
                        raise UserError(_('Material Group is required.'))
                    if is_conversion and not (conversion_legacy_id or conversion_legacy_text):
                        raise UserError(_('Legacy Part Number is required.'))
                    if is_conversion and target_part_text and not existing_new_part_id:
                        raise UserError(_(
                            'Part Number "%s" does not exist. Leave it blank to generate a new one instead.'
                        ) % target_part_text)
                    if not is_conversion and not vals.get('job_number'):
                        raise UserError(_('Job Number is required.'))

                    legacy = self.browse()
                    if is_conversion:
                        if conversion_legacy_id:
                            legacy = self.browse(conversion_legacy_id)
                        else:
                            # Defense in depth: the client resolves legacy
                            # text against its own part list, but that list
                            # can be stale (e.g. someone else just created
                            # this exact code). Reuse it instead of hitting
                            # the part_number unique constraint.
                            legacy = self.search([('part_number', '=', conversion_legacy_text)], limit=1)
                            if not legacy:
                                legacy = self.with_context(skip_job_number_check=True).create({
                                    'material_group_id': vals['material_group_id'],
                                    'part_number': conversion_legacy_text,
                                })

                        # N-N holds only when the target Part Number is
                        # explicitly picked: a legacy code already converted
                        # once (state already 'obsolete') cannot be converted
                        # a second time by auto-generating yet another new
                        # Part Number - only by attaching it to an existing
                        # one via `existing_new_part_id`.
                        if not existing_new_part_id and legacy.state == 'obsolete':
                            raise UserError(_(
                                'This legacy code was already converted once. To link it to another new '
                                'Part Number, pick an existing one instead of leaving Part Number blank.'
                            ))

                    if is_conversion and existing_new_part_id:
                        part = self.browse(existing_new_part_id)
                    else:
                        suffix = self._get_next_suffix(vals['material_group_id'])
                        group = self.env['part_number_manager.material_group'].browse(vals['material_group_id'])
                        vals['sequence_suffix'] = suffix
                        vals['part_number'] = f'{group.code}{suffix}'
                        part = self.with_context(skip_job_number_check=is_conversion).create(vals)

                        for attribute_value in attribute_values:
                            value = attribute_value.get('value')
                            if not value:
                                continue
                            self._create_attribute_value(part, attribute_value['attribute_id'], value)

                    if is_conversion:
                        legacy.state = 'obsolete'
                        self.env['part_number_manager.part_number_mapping'].create({
                            'new_part_id': part.id,
                            'legacy_part_id': legacy.id,
                        })

                    result['success'] = True
                    result['part_id'] = part.id
                    result['part_number'] = part.part_number

            except Exception as exc:
                result['error'] = str(exc)
                _logger.warning('Part creation failed for row %s: %s', idx, exc)

            results.append(result)

        return results
