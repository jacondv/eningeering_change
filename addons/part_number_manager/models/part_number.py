import datetime
import logging
import re

from dateutil import parser as dateutil_parser

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Same range applies to every Material Group - Generate only ever assigns a
# sequence_suffix within [SUFFIX_RANGE_START, SUFFIX_RANGE_END].
SUFFIX_RANGE_START = 0
SUFFIX_RANGE_END = 4999

# The historical export's "Status" column is a different concept entirely
# from our own workflow `state` (draft/active/obsolete) - this is the
# agreed direct translation, everything else is left unset on import.
STATE_BY_STATUS = {
    'development': 'draft',
    'production': 'active',
    'not use': 'obsolete',
}

MAKE_BUY_BY_TYPE = {
    'make': 'make',
    'buy': 'buy',
}


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
        index=True, copy=False,
        help="Generated via the Generate button (material_group.code + sequence_suffix). Never entered by "
             "hand - locked via the form view's own readonly, not this field's own attribute, because a "
             "Python-level readonly=True is silently excluded from the Import screen's field picker "
             "(base_import filters out any field where fields_get()['readonly'] is true), which would "
             "otherwise make Part Number impossible to map when importing historical data.")
    sequence_suffix = fields.Char(size=4, copy=False, readonly=True)
    is_standard_format = fields.Boolean(
        compute='_compute_is_standard_format', store=True, index=True,
        help="Whether part_number is exactly 8 digits (material_group.code + sequence_suffix) - "
             "used to silently hide non-standard codes (legacy imports, mid-conversion drafts, ...) "
             "from the default 'All Part Numbers' list, see web_search_read()/web_read_group() below.")
    legacy_part_number = fields.Char(
        string='Legacy/Old Part Number', copy=False,
        help="Import-only pseudo-field, not shown on the form and never actually written to the "
             "database: it exists solely so Odoo's Import screen offers it as a mappable column (a "
             "field with no real presence in fields_get() can't be selected there at all). load() reads "
             "its raw text from the import row, turns it into a proper legacy Part Number record linked "
             "via the Legacy / New Code Mapping tab, and excludes this field from what actually gets "
             "written - so it always reads back empty, on imported records too.")
    material_group_id = fields.Many2one(
        'part_number_manager.material_group', string='Material Group', index=True,
        help="Required for manual creation (enforced by create_batch_with_generated_number and the form "
             "view, not by this field) - but a historical import may legitimately not know it yet, so it "
             "isn't required at the model level. A part with no Material Group can't be re-Generated a "
             "number from, but its already-assigned part_number stays valid either way.")
    job_number = fields.Many2one('project.project', string='Job Number')
    short_description = fields.Char()
    display_description = fields.Char(
        help="Short internal description used for quick reference/selection on other screens "
             "(e.g. the Hose & Fitting Builder) - independent from Short/Long Description, "
             "entered once per Part when needed.")
    long_description = fields.Html(
        help="Same rich-text field type as project.project's own Description - supports "
             "pasted/embedded images and flexible copy-paste formatting.")
    state = fields.Selection([
        ('draft', 'Development'),
        ('active', 'Production'),
        ('obsolete', 'Not Use'),
    ], default='draft', tracking=True,
        help="Labels shown are Development/Production/Not Use - the underlying values "
             "(draft/active/obsolete) are unchanged, only the display text was renamed.")
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    vendor_ref = fields.Char(string='Vendor Reference')
    make_buy = fields.Selection([
        ('make', 'Make'),
        ('buy', 'Buy'),
    ], string='Make/Buy')
    part_type_id = fields.Many2one(
        'part_number_manager.part_type', string='Part Type',
        help="Set only when this part is built from a BOM.")
    date_created = fields.Datetime(
        string='Date Created', default=fields.Datetime.now,
        help="Defaults to now on manual create - import overrides it with the true historical date.")

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
    is_unlocked = fields.Boolean(
        string='Unlocked for Editing', compute='_compute_is_unlocked',
        inverse='_inverse_is_unlocked',
        help="Not stored - always recomputed on load, so a part is always locked again after "
             "being saved or the page is refreshed. New (unsaved) parts are always unlocked. "
             "See the Edit button on the form.")

    _part_number_unique = models.Constraint(
        'unique(part_number)',
        'This Part Number already exists. The advisory lock in _get_next_suffix should have prevented this.')

    def _compute_is_unlocked(self):
        for part in self:
            part.is_unlocked = not part.id

    def _inverse_is_unlocked(self):
        # No-op: this field is intentionally never persisted - see the help
        # text. The client sets it in-memory (via the Edit button) to unlock
        # the form for the current editing session only.
        pass

    def check_edit_password(self, password):
        """Verify `password` against the current user's own login
        credentials. Used by the Edit-lock button on the Part Number form -
        does not use/require any password other than the logged-in user's
        own account."""
        self.ensure_one()
        credential = {'login': self.env.user.login, 'password': password, 'type': 'password'}
        try:
            self.env.user._check_credentials(credential, {'interactive': True})
        except AccessDenied:
            return False
        return True

    @api.onchange('part_type_id')
    def _onchange_part_type_id_attributes(self):
        # Keeps attribute_value_ids in sync with whatever Part Type is
        # currently selected: drops rows for attributes that don't belong
        # to it (a value left over from a previous Part Type no longer
        # means anything once that Type is switched away from - keeping it
        # around would show a stale attribute with no relation to what the
        # part is now), then adds rows for the new Type's attributes not
        # already present - so the user never has to manually "Add a line"
        # and pick each attribute_id by hand.
        for rec in self:
            allowed_attribute_ids = rec.part_type_id.attribute_ids.ids
            rec.attribute_value_ids = rec.attribute_value_ids.filtered(
                lambda v: v.attribute_id.id in allowed_attribute_ids)
            existing_attribute_ids = rec.attribute_value_ids.mapped('attribute_id').ids
            for attribute in rec.part_type_id.attribute_ids:
                if attribute.id not in existing_attribute_ids:
                    rec.attribute_value_ids += rec.attribute_value_ids.new({'attribute_id': attribute.id})

    @api.onchange('vendor_id')
    def _onchange_vendor_id_make_buy(self):
        # A part sourced from a Vendor is being bought, not made in-house -
        # only flips forward to Buy when a Vendor gets set; removing the
        # Vendor afterward doesn't revert it, since that's not necessarily
        # true (a part can still be bought without a Vendor filled in yet).
        for rec in self:
            if rec.vendor_id:
                rec.make_buy = 'buy'

    @api.depends('supersedes_ids.new_part_id.part_number')
    def _compute_replacement_display(self):
        for rec in self:
            rec.replacement_display = ', '.join(rec.supersedes_ids.mapped('new_part_id.part_number'))

    @api.depends('superseded_ids.legacy_part_id.part_number')
    def _compute_legacy_codes_display(self):
        for rec in self:
            rec.legacy_codes_display = ', '.join(rec.superseded_ids.mapped('legacy_part_id.part_number'))

    @api.depends('part_number')
    def _compute_is_standard_format(self):
        for rec in self:
            rec.is_standard_format = bool(rec.part_number) and rec.part_number.isdigit() and len(rec.part_number) == 8

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

    def _hide_non_standard_format(self, domain):
        """Silently hides any Part Number that isn't the standard 8-digit
        Material Group code + sequence suffix format (legacy/historical
        codes, mid-conversion drafts, ...) from the "All Part Numbers" list -
        never shown as a removable filter chip, per request. Shared by
        web_search_read()/web_read_group() below - the only two read paths
        the list/kanban/group-by view actually uses; internal domain-based
        `search()` calls elsewhere (e.g. the upsert-by-part_number lookup in
        `load()`, suffix-collision checks) are untouched, so non-standard
        codes still behave normally everywhere else in the app.

        Searching by the Part Number field itself (typed in the search bar,
        which ORs it in alongside every other searchable field) already puts
        a 'part_number' leaf in the incoming domain - detected below to skip
        the restriction, so a search for a legacy code's exact text still
        finds it despite the default hiding. Opening a record directly via a
        link (Legacy Codes/Replaced By, Convert page, ...) never goes
        through either method at all, so it's unaffected either way.
        """
        if any(
            isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == 'part_number'
            for leaf in domain
        ):
            return domain
        return list(domain) + [('is_standard_format', '=', True)]

    @api.model
    @api.readonly
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        domain = self._hide_non_standard_format(domain)
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    @api.model
    @api.readonly
    def web_read_group(self, domain, groupby, aggregates=(), **kwargs):
        domain = self._hide_non_standard_format(domain)
        return super().web_read_group(domain, groupby, aggregates, **kwargs)

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
        for i in range(SUFFIX_RANGE_START, SUFFIX_RANGE_END + 1):
            if i not in used:
                return f'{i:04d}'
        raise UserError(_('This Material Group has used up all available codes (%(start)s-%(end)s).') % {
            'start': f'{SUFFIX_RANGE_START:04d}', 'end': f'{SUFFIX_RANGE_END:04d}',
        })

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
        Legacy Part Number and Vendor may both be created on the fly, via
        `conversion_legacy_text`/`vendor_name` when the autocomplete had no
        match. Job Number is search-only (never created here) and only
        mandatory for rows that create a brand new part outside of a
        conversion.
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
                    vendor_name = vals.pop('vendor_name', None)
                    is_conversion = bool(conversion_legacy_id or conversion_legacy_text)

                    if not vals.get('vendor_id') and vendor_name:
                        # Same find-or-create-by-exact-name approach as the
                        # Old Part Number field and the historical load()
                        # import - an unmatched Vendor typed here is a new
                        # Contact, not an error.
                        vendor = self.env['res.partner'].search([('name', '=', vendor_name)], limit=1)
                        if not vendor:
                            vendor = self.env['res.partner'].create({'name': vendor_name})
                        vals['vendor_id'] = vendor.id

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

    def _sync_legacy_codes(self, legacy_by_part_number):
        """For each imported row that carried a legacy/old code, find or
        create that legacy Part Number - mirroring
        `create_batch_with_generated_number`'s own on-the-fly legacy
        creation for the manual Convert flow - and link it via
        `part_number_mapping`, exactly as if a human had done the Convert
        by hand. Idempotent: an already-existing identical mapping is left
        alone, so re-importing the same file doesn't duplicate anything or
        error - and a row that (incorrectly) lists its own Part Number as
        its own legacy code is reported rather than linked to itself.
        """
        if not legacy_by_part_number:
            return []
        mapping_model = self.env['part_number_manager.part_number_mapping']
        messages = []
        # Both prefetched once instead of one search() per row - refreshed
        # in-loop below whenever a legacy Part Number gets created, so a
        # legacy code repeated across rows in the same batch still resolves
        # to the record just created for it, same as the old per-row search.
        parts_by_number = {p.part_number: p for p in self.search(
            [('part_number', 'in', list(legacy_by_part_number.keys()))])}
        legacies_by_text = {p.part_number: p for p in self.search(
            [('part_number', 'in', [text for text, _ in legacy_by_part_number.values()])])}
        for part_number, (legacy_text, group_id) in legacy_by_part_number.items():
            part = parts_by_number.get(part_number)
            if not part:
                continue
            legacy = legacies_by_text.get(legacy_text)
            if legacy and legacy.id == part.id:
                messages.append({
                    'type': 'error',
                    'message': _(
                        "Part Number '%(pn)s' lists itself ('%(legacy)s') as its own legacy code - "
                        "the link was skipped.") % {'pn': part_number, 'legacy': legacy_text},
                })
                continue
            if not legacy:
                legacy = self.with_context(skip_job_number_check=True).create({
                    'material_group_id': group_id,
                    'part_number': legacy_text,
                })
                legacies_by_text[legacy_text] = legacy
            existing_mapping = mapping_model.search([
                ('new_part_id', '=', part.id), ('legacy_part_id', '=', legacy.id),
            ], limit=1)
            if not existing_mapping:
                mapping_model.create({'new_part_id': part.id, 'legacy_part_id': legacy.id})
            if legacy.state != 'obsolete':
                legacy.state = 'obsolete'
        return messages

    @api.model
    def load(self, fields, data):
        """Imports a historical Part Number export: already-assigned real
        numbers, not the Generate-button flow. Same two structural
        findings as the sibling `partnumber_manager` addon's `load()`
        override apply here (see that addon's tech spec for the full
        write-up):
        - native Import only matches an existing record for update via an
          External/Database ID column, never an arbitrary unique field -
          so re-importing an already-imported file would try to *create*
          every row again and fail on the `part_number` unique constraint.
          Fixed by always upserting by `part_number` itself, looked up and
          injected as `.id` before delegating to `super().load()`.
        - `load()` is all-or-nothing: a single 'error' message anywhere
          discards the *entire* batch. Anything this method can't safely
          resolve is therefore excluded *before* calling `super().load()`,
          with its own error appended to the final result afterwards - so
          unrelated valid rows still import in the same call.

        Per-column handling (Material Group, Vendor, Job Number, Status,
        Type, Date, legacy code) is commented individually below, right
        where each one is resolved.
        """
        if 'part_number' not in fields:
            return super().load(fields, data)

        field_list = list(fields)
        rows = [dict(zip(field_list, row)) for row in data]
        for row in rows:
            if isinstance(row.get('part_number'), str):
                row['part_number'] = row['part_number'].strip()

        partner_model = self.env['res.partner']
        project_model = self.env['project.project']
        # Prefetched once (Material Group is a small, bounded config list,
        # unlike Vendor/Job Number below) instead of one search() per row.
        groups_by_code = {g.code: g for g in self.env['part_number_manager.material_group'].search([])}

        resolved_rows = []
        conflict_messages = []
        legacy_by_part_number = {}

        for row in rows:
            part_number = row.get('part_number')
            if not part_number:
                conflict_messages.append({
                    'type': 'error',
                    'message': _('A row has no Part Number - it was not imported.'),
                })
                continue

            # A blank Material Group cell is accepted - some historical
            # rows genuinely don't have one on file yet - but a non-blank
            # cell that doesn't match any existing Material Group is a
            # real data problem (typo, or the Group hasn't been declared
            # yet under Configuration) and is reported instead of guessed
            # at or silently dropped.
            group = False
            raw_group = row.get('material_group_id')
            if isinstance(raw_group, str) and raw_group.strip():
                # Match on the leading 4-digit code alone - the source
                # file's separator/spacing after it is inconsistent (e.g.
                # "1202-Boom & Parts" has no space around the dash, unlike
                # our own "code - description" display format).
                code_match = re.match(r'\s*(\d{4})', raw_group)
                group = groups_by_code.get(code_match.group(1), False) if code_match else False
                if not group:
                    conflict_messages.append({
                        'type': 'error',
                        'message': _(
                            "Part Number '%(pn)s': Material Group '%(raw)s' does not match any existing "
                            "Material Group - it was not imported.") % {'pn': part_number, 'raw': raw_group},
                    })
                    continue
                if not part_number.startswith(group.code):
                    conflict_messages.append({
                        'type': 'error',
                        'message': _(
                            "Part Number '%(pn)s' does not start with its Material Group's own code "
                            "'%(code)s' - it was not imported.") % {'pn': part_number, 'code': group.code},
                    })
                    continue

            row = dict(row)
            row['material_group_id'] = str(group.id) if group else ''
            row['sequence_suffix'] = part_number[len(group.code):] if group else ''
            resolved_rows.append(row)

            raw_legacy = row.get('legacy_part_number')
            if isinstance(raw_legacy, str) and raw_legacy.strip():
                legacy_by_part_number[part_number] = (raw_legacy.strip(), group.id if group else False)

        load_fields = [f for f in field_list if f not in ('legacy_part_number', 'id', '.id')]
        load_fields.append('sequence_suffix')
        load_data = [[row.get(f) or '' for f in load_fields] for row in resolved_rows]

        pn_idx = load_fields.index('part_number')
        part_numbers = {row[pn_idx] for row in load_data if row[pn_idx]}
        existing = {p.part_number: p.id for p in self.search([('part_number', 'in', list(part_numbers))])}

        # Two rows in the *same* file sharing a brand-new (not-yet-existing)
        # Part Number would both resolve to `.id` = '' below and both try to
        # CREATE in the same super().load() call - the second one then hits
        # the unique constraint against the first, which super().load()
        # can't attribute to a specific row, so it gets misreported against
        # row 1 regardless of which Part Number actually collided. Caught
        # here instead, against a real row/Part Number, before that happens;
        # the first occurrence still imports normally.
        seen_new_part_numbers = set()
        duplicate_row_indices = set()
        for i, row in enumerate(load_data):
            value = row[pn_idx]
            if value and value not in existing:
                if value in seen_new_part_numbers:
                    duplicate_row_indices.add(i)
                else:
                    seen_new_part_numbers.add(value)
        if duplicate_row_indices:
            for i in sorted(duplicate_row_indices):
                conflict_messages.append({
                    'type': 'error',
                    'message': _(
                        "Part Number '%(pn)s' appears more than once in this import file - "
                        "only its first occurrence was imported; fix the duplicate rows and "
                        "re-import them separately."
                    ) % {'pn': load_data[i][pn_idx]},
                })
            load_data = [row for i, row in enumerate(load_data) if i not in duplicate_row_indices]

        load_fields.append('.id')
        for row in load_data:
            value = row[pn_idx]
            row.append(str(existing[value]) if value in existing else '')

        if 'material_group_id' in load_fields:
            load_fields[load_fields.index('material_group_id')] = 'material_group_id/.id'

        if 'vendor_id' in load_fields:
            idx = load_fields.index('vendor_id')
            # Memoized by name (not prefetched whole, unlike Material Group -
            # res.partner is unbounded) so a Vendor repeated across many rows
            # only costs one search()/create() instead of one per row.
            vendor_ids_by_name = {}
            for row in load_data:
                raw = row[idx]
                if raw:
                    name = raw.strip()
                    if name not in vendor_ids_by_name:
                        record = partner_model.search([('name', '=', name)], limit=1)
                        if not record:
                            record = partner_model.create({'name': name})
                        vendor_ids_by_name[name] = record.id
                    row[idx] = str(vendor_ids_by_name[name])
            load_fields[idx] = 'vendor_id/.id'

        if 'job_number' in load_fields:
            idx = load_fields.index('job_number')
            # Same memoization as Vendor above - a Job Number repeated
            # across many rows only costs one search().
            job_ids_by_name = {}
            for row in load_data:
                raw = row[idx]
                row[idx] = ''
                if raw:
                    name = raw.strip()
                    if name not in job_ids_by_name:
                        record = project_model.search([('name', '=', name)], limit=1)
                        job_ids_by_name[name] = record.id if record else ''
                    row[idx] = str(job_ids_by_name[name]) if job_ids_by_name[name] else ''
            load_fields[idx] = 'job_number/.id'

        if 'state' in load_fields:
            idx = load_fields.index('state')
            for row in load_data:
                raw = row[idx]
                row[idx] = STATE_BY_STATUS.get(raw.strip().lower(), '') if raw else ''

        if 'make_buy' in load_fields:
            idx = load_fields.index('make_buy')
            for row in load_data:
                raw = row[idx]
                row[idx] = MAKE_BUY_BY_TYPE.get(raw.strip().lower(), '') if raw else ''

        if 'date_created' in load_fields:
            idx = load_fields.index('date_created')
            for row in load_data:
                raw = row[idx]
                if not raw:
                    continue
                try:
                    # A .xlsx source hands date-formatted cells to us as
                    # real datetime/date objects (not text) - dateutil.parse
                    # only accepts strings, so those must be used as-is
                    # instead of reparsed. A .csv source (or an Excel column
                    # not formatted as a date) still comes through as text,
                    # in the source's month-first format - see the docstring
                    # above for why dateutil is needed for that case.
                    if isinstance(raw, datetime.datetime):
                        parsed = raw
                    elif isinstance(raw, datetime.date):
                        parsed = datetime.datetime.combine(raw, datetime.time())
                    else:
                        parsed = dateutil_parser.parse(raw)
                    row[idx] = parsed.strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, OverflowError, TypeError):
                    row[idx] = ''

        # Historical rows routinely have no resolvable Job Number (the real
        # export mixes in values that were never Job Numbers to begin
        # with) - create()'s own "Job Number is required" guard exists for
        # the manual entry page, not for a bulk historical import.
        result = super(PartNumber, self.with_context(skip_job_number_check=True)).load(load_fields, load_data)

        if result['ids']:
            conflict_messages += self._sync_legacy_codes(legacy_by_part_number)

        if conflict_messages:
            result = dict(result, messages=list(result['messages']) + conflict_messages)
        return result
