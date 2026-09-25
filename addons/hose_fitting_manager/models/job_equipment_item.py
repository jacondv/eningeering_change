from odoo import _, api, fields, models

PART_ATTRIBUTE_VALUE_MODEL = 'part_number_manager.part_attribute_value'
PART_NUMBER_MODEL = 'part_number_manager.part_number'


class JobEquipmentItem(models.Model):
    """One physical equipment instance on a Job (e.g. one specific Pump,
    one specific Valve) that a Job Hose Line can be Wired From/To. Scoped
    per Job so the Wire wizard's pickers only ever offer this Job's own
    equipment, never the whole Part Number database.

    The same Part Number can appear on more than one row (two physically
    separate Pumps of the same model) - each row is its own instance, with
    its own Description EN/VN and its own independent set of used/open
    Ports. Added either by pasting a Part Number/Quantity block (see
    equipment_items.js) or one at a time via "Add Item" - a Quantity > 1 on
    paste is expanded into that many separate rows, numbering the
    Description "(2)", "(3)"... from the second copy on, since each row
    must end up describing exactly one wireable instance.
    """
    _name = 'hose_fitting_manager.job_equipment_item'
    _description = 'Job Equipment Item'
    _order = 'job_number, sequence, id'

    job_number = fields.Many2one('project.project', string='Job Number', required=True, index=True)
    sequence = fields.Integer(default=10)
    part_id = fields.Many2one('part_number_manager.part_number', string='Part', required=True)
    # Defaulted from the Part's own Display Description (EN)/(VN) at
    # creation time (paste or Add Item - see build_descriptions below),
    # never typed by hand - but still an ordinary stored field, editable
    # afterward, since the same Part can appear as several distinct
    # instances that are worth telling apart (e.g. "Pump A" vs "Pump B").
    # Wire reads these straight through onto the Job Hose Line's own
    # Description EN/VN (see wire_wizard.py) - EN from description_en, VN
    # from description_vn, never cross-mixed.
    description_en = fields.Char(string='Description (EN)', required=True)
    description_vn = fields.Char(string='Description (VN)', required=True)

    port_ids = fields.Many2many(
        PART_ATTRIBUTE_VALUE_MODEL, compute='_compute_port_ids', string='Ports',
        help="This Item's Part's own \"Port\" attribute values (Part Attributes) - one entry "
             "per physical port on the Part.")
    open_ports = fields.Char(
        string='Open Ports', compute='_compute_port_status',
        help="Port labels on this Item not yet used as a From/To on any Job Hose Line Wired in "
             "the same Job - i.e. still free to wire. Blank once every Port is wired, or if the "
             "Part has no Port attribute at all.")
    used_ports = fields.Char(
        string='Used Ports', compute='_compute_port_status',
        help="Port labels on this Item already used as a From/To on a Wired Job Hose Line in the "
             "same Job.")

    @api.depends('description_en', 'part_id.part_number')
    def _compute_display_name(self):
        # No Char field of its own doubles as the default display_name
        # source (unlike most models) - without this override, the Wire
        # wizard's From/To Item pickers would show an unhelpful "Job
        # Equipment Item, 123" instead of this instance's own Description.
        # EN only here - this is a UI picker label, not the bilingual Wire
        # output (see description_preview_en/vn on wire_wizard.py).
        for rec in self:
            rec.display_name = (
                f'{rec.description_en} ({rec.part_id.part_number})' if rec.part_id else rec.description_en)

    @api.depends('part_id.attribute_value_ids.attribute_id.name')
    def _compute_port_ids(self):
        for rec in self:
            rec.port_ids = rec.part_id.attribute_value_ids.filtered(
                lambda v: v.attribute_id.name == 'Port')

    @api.depends('port_ids', 'job_number')
    def _compute_port_status(self):
        # Batched across all records in this recordset (one search per
        # distinct Job, not two searches per record) - a per-record
        # get_open_port_ids() call here made adding even a handful of Items
        # visibly slow, since every row on screen re-triggers this compute.
        used_ports_by_item = {}
        job_ids = self.job_number.ids
        if job_ids:
            hose_line_model = self.env['hose_fitting_manager.job_hose_line']
            lines = hose_line_model.search([('job_number', 'in', job_ids)])
            for line in lines:
                if line.from_item_id and line.from_port_id:
                    used_ports_by_item.setdefault(line.from_item_id.id, set()).add(line.from_port_id.id)
                if line.to_item_id and line.to_port_id:
                    used_ports_by_item.setdefault(line.to_item_id.id, set()).add(line.to_port_id.id)

        for rec in self:
            used_ids = used_ports_by_item.get(rec.id, set())
            open_values = rec.port_ids.filtered(lambda v: v.id not in used_ids)
            used_values = rec.port_ids.filtered(lambda v: v.id in used_ids)
            rec.open_ports = ', '.join(open_values.mapped('display_value'))
            rec.used_ports = ', '.join(used_values.mapped('display_value'))

    @api.model
    def get_port_board_data(self, job_id):
        """Batched, read-only snapshot for the Builder page's Port
        Connection Board: every Job Equipment Item for `job_id`, each with
        its own Ports carrying id/label/status - and, for a used Port, the
        other end's Item/Port labels plus the job_hose_line id, so the
        client can highlight that line's recap row without a second round
        trip. Same one-search-per-Job batching as _compute_port_status, not
        N+1 per item/port. "Reserved" (claimed by another still-unsaved
        Builder row) is deliberately not computed here - that's a
        client-side-only concept the Builder page derives from its own
        pending rows, so this only ever reports 'open'/'used'.
        """
        items = self.search([('job_number', '=', job_id)])
        if not items:
            return []

        hose_line_model = self.env['hose_fitting_manager.job_hose_line']
        lines = hose_line_model.search([('job_number', '=', job_id)])

        usage_by_port_id = {}
        for line in lines:
            if line.from_item_id and line.from_port_id:
                usage_by_port_id[line.from_port_id.id] = {
                    'job_hose_line_id': line.id,
                    'connected_item_id': line.to_item_id.id,
                    'connected_item_label': line.to_item_id.display_name,
                    'connected_port_label': line.to_port_id.display_value,
                }
            if line.to_item_id and line.to_port_id:
                usage_by_port_id[line.to_port_id.id] = {
                    'job_hose_line_id': line.id,
                    'connected_item_id': line.from_item_id.id,
                    'connected_item_label': line.from_item_id.display_name,
                    'connected_port_label': line.from_port_id.display_value,
                }

        result = []
        for item in items:
            ports = []
            for value in item.port_ids:
                usage = usage_by_port_id.get(value.id)
                ports.append({
                    'id': value.id,
                    'label': value.display_value,
                    'status': 'used' if usage else 'open',
                    'connected_item_id': usage['connected_item_id'] if usage else False,
                    'connected_item_label': usage['connected_item_label'] if usage else '',
                    'connected_port_label': usage['connected_port_label'] if usage else '',
                    'job_hose_line_id': usage['job_hose_line_id'] if usage else False,
                })
            result.append({
                'id': item.id,
                'part_number': item.part_id.part_number,
                'description_en': item.description_en,
                'ports': ports,
            })
        return result

    def get_open_port_ids(self, exclude_line=None):
        """This Item's own Port attribute_value ids minus whichever are
        already used as a From/To Port on another Wired Job Hose Line in
        the same Job. `exclude_line` lets the Wire wizard still offer a
        line's own current From/To Port when re-wiring that same line -
        a port isn't "taken" by the very connection it's already part of.
        """
        self.ensure_one()
        if not self.port_ids:
            return []
        hose_line_model = self.env['hose_fitting_manager.job_hose_line']
        domain = [('job_number', '=', self.job_number.id)]
        if exclude_line:
            domain.append(('id', '!=', exclude_line.id))
        used_ids = set(hose_line_model.search(domain + [('from_item_id', '=', self.id)]).from_port_id.ids)
        used_ids |= set(hose_line_model.search(domain + [('to_item_id', '=', self.id)]).to_port_id.ids)
        return (self.port_ids - self.env[PART_ATTRIBUTE_VALUE_MODEL].browse(used_ids)).ids

    @api.model
    def _parse_paste_quantity(self, text):
        try:
            return max(1, int(float(text or '1')))
        except ValueError:
            return None

    @api.model
    def _default_descriptions(self, part, copy_idx=1, quantity=1):
        """The (Description EN, Description VN) a new Item for `part` starts
        with - always the Part's own Display Description EN/VN (falling back
        to the Part Number itself if a Part has neither set), never typed by
        hand. When `quantity` > 1 (more than one copy from the same paste
        line), every copy - including the first - is numbered "(1)", "(2)"...
        so instances of the same Part stay tellable apart while still being
        renamed later if needed. `quantity` == 1 (no sibling copies) gets no
        suffix at all.
        """
        base_en = part.display_description or part.part_number
        base_vn = part.display_description_vn or base_en
        if quantity <= 1:
            return base_en, base_vn
        return f'{base_en} ({copy_idx})', f'{base_vn} ({copy_idx})'

    @api.model
    def parse_paste(self, paste_text):
        """Parses an Excel paste block (Part Number / Quantity, tab-separated,
        one item per line - a plain Excel copy, no Description column) into a
        *preview* - nothing is created here. Description EN/VN always come
        from the Part's own Display Description (see _default_descriptions),
        never from the pasted text. Quantity > 1 expands into that many
        preview rows. A bad line (unknown Part Number, invalid Quantity) is
        skipped and reported, never discarding the rest of an otherwise-good
        paste. Called the moment a paste lands on the Equipment Items page's
        Add Item box (see equipment_items.js) - the parsed rows sit in the
        page's own pending list, only becoming real records once its Save
        button actually creates them.
        """
        part_model = self.env[PART_NUMBER_MODEL]
        rows = []
        errors = []
        lines = [line for line in (paste_text or '').splitlines() if line.strip()]

        for idx, line in enumerate(lines, start=1):
            columns = line.split('\t')
            part_number = (columns[0] if columns else '').strip()
            if not part_number:
                continue
            quantity = self._parse_paste_quantity(columns[1] if len(columns) > 1 else '1')

            part = part_model.search([('part_number', '=', part_number)], limit=1)
            if not part:
                errors.append(_('Line %s: Part Number "%s" not found - skipped.') % (idx, part_number))
                continue
            if quantity is None:
                errors.append(_('Line %s: invalid Quantity - skipped.') % (idx,))
                continue

            for copy_idx in range(1, quantity + 1):
                description_en, description_vn = self._default_descriptions(part, copy_idx, quantity)
                rows.append({
                    'part_id': part.id,
                    'part_label': f'{description_en} ({part.part_number})',
                    'description_en': description_en,
                    'description_vn': description_vn,
                })

        return {'rows': rows, 'errors': errors}
