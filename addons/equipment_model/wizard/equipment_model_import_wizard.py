import base64
import io
from datetime import date

import openpyxl
import xlsxwriter

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import escape_psql

# The one layout both ways: what Export writes is what Import reads back.
COLUMNS = ['Group', 'Product Family', 'Model', 'Parent Model', 'Job']
KEYS = ['group', 'family', 'model', 'parent', 'job']
STATUSES = [
    ('create', 'Create'),
    ('update', 'Update'),
    ('unchanged', 'No change'),
    ('error', 'Error'),
]
INSTRUCTIONS = [
    "One row per Model and Job. Group, Product Family and Model are matched by name, ignoring case:",
    "a name that exists is updated, a new one is created. Re-importing an export never creates duplicates.",
    "A Product Family moves to the Group on its row. A Model moves to the Product Family on its row.",
    "A Model without a Product Family takes its Parent Model's.",
    "Job must be an existing Job: the import links it to the row's Model, it never creates Jobs.",
    "An empty cell changes nothing: it does not clear what is already set.",
]


class _PreviewDone(Exception):
    """Ends a preview by rolling back everything it did."""


class EquipmentModelImportWizard(models.TransientModel):
    _name = 'equipment.model.import.wizard'
    _description = 'Import Groups, Product Families, Models and Jobs'

    file = fields.Binary(string='Excel File')
    filename = fields.Char()
    state = fields.Selection([('upload', 'Upload'), ('preview', 'Preview'), ('done', 'Done')], default='upload')
    line_ids = fields.One2many('equipment.model.import.line', 'wizard_id')
    create_count = fields.Integer()
    update_count = fields.Integer()
    unchanged_count = fields.Integer()
    error_count = fields.Integer()
    export_file = fields.Binary(attachment=False)
    export_filename = fields.Char()

    # Export

    @api.model
    def action_export(self):
        wizard = self.create({
            'export_file': base64.b64encode(self._export_workbook()),
            'export_filename': f"equipment_models_{date.today():%Y%m%d}.xlsx",
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/{self._name}/{wizard.id}/export_file/{wizard.export_filename}?download=true",
            'target': 'self',
        }

    def _export_rows(self):
        rows = []
        Project = self.env['project.project']
        job_domain = Project._equipment_job_domain()
        models_seen = self.env['equipment.model']
        for group in self.env['equipment.model.category'].search([]):
            if not group.family_ids:
                rows.append([group.name, '', '', '', ''])
            for family in group.family_ids.sorted('name'):
                if not family.model_ids:
                    rows.append([group.name, family.name, '', '', ''])
                for model in family.model_ids.sorted('name'):
                    rows += self._model_rows(model, job_domain, group.name, family.name)
                    models_seen |= model
        for model in self.env['equipment.model'].search([('id', 'not in', models_seen.ids)]):
            rows += self._model_rows(model, job_domain, '', '')
        return rows

    def _model_rows(self, model, job_domain, group, family):
        jobs = self.env['project.project'].search(job_domain + [('model_id', '=', model.id)], order='name')
        return [[group, family, model.name, model.parent_id.name or '', job.name] for job in jobs] \
            or [[group, family, model.name, model.parent_id.name or '', '']]

    def _export_workbook(self):
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        header = workbook.add_format({'bold': True, 'bg_color': '#DDE3EE', 'border': 1})
        sheet = workbook.add_worksheet('Equipment Models')
        for col, (title, width) in enumerate(zip(COLUMNS, [14, 20, 26, 26, 30])):
            sheet.write(0, col, title, header)
            sheet.set_column(col, col, width)
        for row, values in enumerate(self._export_rows(), start=1):
            sheet.write_row(row, 0, values)
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, max(1, sheet.dim_rowmax or 1), len(COLUMNS) - 1)
        notes = workbook.add_worksheet('How to import')
        notes.set_column(0, 0, 110)
        for row, text in enumerate(INSTRUCTIONS):
            notes.write(row, 0, text)
        workbook.close()
        return buffer.getvalue()

    # Import

    def action_preview(self):
        self.ensure_one()
        rows = self._read_rows()
        try:
            with self.env.cr.savepoint():
                results = self._import_rows(rows)
                raise _PreviewDone
        except _PreviewDone:
            pass
        self.env.invalidate_all()
        self._show(results, 'preview')
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        results = self._import_rows(self._read_rows())
        if any(result['status'] == 'error' for result in results):
            # The data changed since the preview: nothing of this is kept.
            raise UserError(_("The import now finds errors it did not find in the preview. Preview it again."))
        self._show(results, 'done')
        return self._reopen()

    def action_back(self):
        self.write({'state': 'upload', 'line_ids': [(5, 0, 0)], 'file': False, 'filename': False})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
            'name': _("Import Equipment Models"),
        }

    def _show(self, results, state):
        counts = {status: 0 for status, _label in STATUSES}
        for result in results:
            counts[result['status']] += 1
        self.write({
            'state': state,
            'line_ids': [(5, 0, 0)] + [(0, 0, result) for result in results],
            'create_count': counts['create'],
            'update_count': counts['update'],
            'unchanged_count': counts['unchanged'],
            'error_count': counts['error'],
        })

    def _read_rows(self):
        if not self.file:
            raise UserError(_("Choose an Excel file first."))
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(self.file)), read_only=True, data_only=True)
        except Exception:
            raise UserError(_("This is not an Excel (.xlsx) file. Use Export to get one in the right layout.")) from None
        sheet = workbook.worksheets[0]
        lines = sheet.iter_rows(values_only=True)
        header = [self._cell_text(cell).lower() for cell in next(lines, [])]
        expected = [title.lower() for title in COLUMNS]
        missing = [title for title in COLUMNS if title.lower() not in header]
        if missing:
            raise UserError(_(
                "The first row must hold the column titles %(columns)s. Missing: %(missing)s.",
                columns=", ".join(COLUMNS), missing=", ".join(missing)))
        positions = [header.index(title) for title in expected]
        rows = []
        for number, line in enumerate(lines, start=2):
            values = {key: self._cell_text(line[position]) if position < len(line) else ''
                      for key, position in zip(KEYS, positions)}
            if any(values.values()):
                rows.append({'row': number, **values})
        workbook.close()
        if not rows:
            raise UserError(_("The file has no rows to import."))
        return rows

    @staticmethod
    def _cell_text(value):
        if value is None:
            return ''
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value).strip()

    def _import_rows(self, rows):
        """Groups, Families and Models first, then what refers to them (parents,
        Jobs), so a row may name a Parent Model created further down."""
        results = {row['row']: {**row, 'status': 'unchanged', 'notes': []} for row in rows}
        seen = {}
        for row in rows:
            self._run_row(results[row['row']], lambda result, row=row: self._import_structure(row, result, seen))
        for row in rows:
            self._run_row(results[row['row']], lambda result, row=row: self._import_links(row, result))
        return [self._result_line(result) for result in results.values()]

    def _run_row(self, result, step):
        if result['status'] == 'error':
            return
        try:
            with self.env.cr.savepoint():
                step(result)
        except (UserError, ValidationError) as error:
            result['status'] = 'error'
            result['notes'] = [str(error.args[0] if error.args else error)]

    def _result_line(self, result):
        return {
            'row': result['row'],
            'group_name': result['group'],
            'family_name': result['family'],
            'model_name': result['model'],
            'parent_name': result['parent'],
            'job_name': result['job'],
            'status': result['status'],
            'message': "; ".join(result['notes']),
        }

    def _import_structure(self, row, result, seen):
        group = family = None
        if row['group']:
            group = self._get_or_create('equipment.model.category', row['group'], {}, result, _("Group"))
        if row['family']:
            family = self._find('equipment.model.family', row['family'])
            if not family and not group:
                raise UserError(_("New Product Family %s needs a Group on its row.", row['family']))
            family = self._get_or_create('equipment.model.family', row['family'], {'category_id': group.id} if group else {}, result, _("Product Family"))
            if group and family.category_id != group:
                self._update(family, {'category_id': group.id}, result, _("Product Family %(name)s moved to Group %(group)s", name=family.name, group=group.name))
        elif group and row['model']:
            raise UserError(_("A row with a Group and a Model needs the Product Family between them."))
        if row['model']:
            # A Model may be on several rows, one per Job. Empty cells change
            # nothing, so only two filled-in values that differ conflict.
            earlier = seen.setdefault(row['model'].lower(), {})
            for key, label in (('family', _("Product Family")), ('parent', _("Parent Model"))):
                value = row[key].lower()
                if value and earlier.get(key, value) != value:
                    raise UserError(_("Model %(model)s has another %(label)s on an earlier row.", model=row['model'], label=label))
                if value:
                    earlier[key] = value
            model = self._get_or_create('equipment.model', row['model'], {'family_id': family.id} if family else {}, result, _("Model"))
            if family and model.family_id != family:
                self._update(model, {'family_id': family.id}, result, _("Model %(name)s moved to Product Family %(family)s", name=model.name, family=family.name))

    def _import_links(self, row, result):
        model = row['model'] and self._find('equipment.model', row['model'])
        if row['parent']:
            if not model:
                raise UserError(_("A Parent Model needs a Model on its row."))
            parent = self._find('equipment.model', row['parent'])
            if not parent:
                raise UserError(_("Parent Model %s does not exist and is on no row of this file.", row['parent']))
            if model.parent_id != parent:
                self._update(model, {'parent_id': parent.id}, result, _("Parent Model of %(name)s set to %(parent)s", name=model.name, parent=parent.name))
        if model and not model.family_id and model.parent_id:
            family = model.parent_id._effective_family()
            if family:
                self._update(model, {'family_id': family.id}, result, _("Model %(name)s takes Product Family %(family)s from its Parent Model", name=model.name, family=family.name))
        if row['job']:
            if not model:
                raise UserError(_("A Job needs a Model on its row."))
            job = self.env['project.project'].with_context(active_test=False).search(
                self.env['project.project']._equipment_job_domain() + [('name', '=ilike', escape_psql(row['job']))], limit=1)
            if not job:
                raise UserError(_("Job %s does not exist. The import links existing Jobs only.", row['job']))
            if job.model_id != model:
                self._update(job, {'model_id': model.id}, result, _("Job %(job)s linked to Model %(model)s", job=job.name, model=model.name))

    def _find(self, model_name, name):
        return self.env[model_name].with_context(active_test=False).search(
            [('name', '=ilike', escape_psql(name))], limit=1)

    def _get_or_create(self, model_name, name, values, result, label):
        record = self._find(model_name, name)
        if record:
            return record
        result['status'] = 'create'
        result['notes'].append(_("%(label)s %(name)s created", label=label, name=name))
        return self.env[model_name].create({'name': name, **values})

    def _update(self, record, values, result, note):
        record.write(values)
        if result['status'] == 'unchanged':
            result['status'] = 'update'
        result['notes'].append(note)


class EquipmentModelImportLine(models.TransientModel):
    _name = 'equipment.model.import.line'
    _description = 'Equipment Model Import Row'
    _order = 'rank, row'

    wizard_id = fields.Many2one('equipment.model.import.wizard', required=True, ondelete='cascade')
    row = fields.Integer()
    # Errors first, then what changes: they would be lost among the unchanged rows.
    rank = fields.Integer(compute='_compute_rank', store=True)
    # Not `parent`, `model`...: `parent` is taken in the form's evaluation context.
    group_name = fields.Char(string='Group')
    family_name = fields.Char(string='Product Family')
    model_name = fields.Char(string='Model')
    parent_name = fields.Char(string='Parent Model')
    job_name = fields.Char(string='Job')
    status = fields.Selection(STATUSES)
    message = fields.Char()

    @api.depends('status')
    def _compute_rank(self):
        ranks = {status: rank for rank, (status, _label) in enumerate(STATUSES)}
        ranks['error'] = -1
        for line in self:
            line.rank = ranks.get(line.status, len(ranks))
