from odoo import _, api, models
from odoo.exceptions import UserError

from .qc_checksheet import GROUP_AUTHOR
from .qc_checksheet_change import RUNNING_CHANGE_EXCLUDED_STATES
from .qc_checksheet_editor import COPY_SOURCE_LIMIT


class QcChecksheet(models.Model):
    """Server side of the Model QC page (static/src/model): every check sheet
    of one Model, by Type, and creating the missing ones in one go. This is
    where sheets are written and revised; Jobs only print them."""
    _inherit = 'qc.checksheet'

    @api.model
    def _model_sheets_by_type(self, model):
        sheets = {}
        for sheet in self.search([('model_id', '=', model.id)]).sorted('revision'):
            sheets.setdefault(sheet.type_id, self.browse())
            sheets[sheet.type_id] |= sheet
        return sheets

    @api.model
    def _sheet_summary(self, sheet):
        state_labels = dict(self._fields['state'].selection)
        return {
            'id': sheet.id,
            'revision': sheet.revision,
            'state': sheet.state,
            'state_label': state_labels[sheet.state],
            'layout': sheet.checksheet_type,
        }

    @api.model
    def model_overview(self, model_id):
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        if not model:
            raise UserError(_("This Model no longer exists."))
        sheets_by_type = self._model_sheets_by_type(model)
        # Archived Types still show the sheets the Model already has.
        types = self.env['qc.checksheet.type'].search([]) | self.env['qc.checksheet.type'].union(*sheets_by_type)
        types = types.filtered(lambda t: t.required or t in sheets_by_type).sorted(
            lambda t: (not t.required, t.sequence, t.name))
        JobSheet = self.env['qc.job.checksheet'].sudo()
        jobs_by_type = dict(JobSheet._read_group(
            [('model_id', '=', model.id)], ['type_id'], ['job_id:count_distinct']))
        # Jobs on a Revision that is no longer the current one.
        old_by_type = dict(JobSheet._read_group(
            [('model_id', '=', model.id), ('checksheet_id.state', '=', 'superseded')],
            ['type_id'], ['job_id:count_distinct']))
        rows = []
        for checksheet_type in types:
            revisions = sheets_by_type.get(checksheet_type, self.browse())
            # The Revision in use; before any Release, the only one there is.
            current = revisions.filtered(lambda s: s.state == 'released')[:1] or revisions[-1:]
            latest = revisions[-1:]
            rows.append({
                'type_id': checksheet_type.id,
                'type_name': checksheet_type.name,
                'required': checksheet_type.required,
                'layout': checksheet_type.layout,
                'number': current.reference or '',
                'header': current.name or '',
                # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
                'current': self._sheet_summary(current) if current else False,
                'next': self._sheet_summary(latest) if latest != current else False,
                'jobs': jobs_by_type.get(checksheet_type, 0),
                'old_jobs': old_by_type.get(checksheet_type, 0),
            })
        self.env['engineering.change'].flush_model(['affected_model_ids'])
        running = self.env['engineering.change'].search([
            ('affected_model_ids', 'in', model.id), ('state', 'not in', list(RUNNING_CHANGE_EXCLUDED_STATES)),
        ], order='id desc')
        return {
            'id': model.id,
            'name': model.display_name,
            'family': model.family_id.name or '',
            'job_count': self.env['project.project'].sudo().with_context(active_test=False).search_count(
                [('model_id', '=', model.id)]),
            'released': sum(1 for row in rows if row['required'] and row['current'] and row['current']['state'] == 'released'),
            'required': sum(1 for row in rows if row['required']),
            'rows': rows,
            'changes': [self._change_summary(change) for change in running],
            'can_author': self.env.user.has_group(GROUP_AUTHOR),
        }

    @api.model
    def model_sheet_sources(self, model_id, type_ids):
        """For each Type to create: what it can be copied from, and the one picked
        by default - the latest Released sheet of the same Type. Sheets of
        another Type with the same layout are offered too, but never picked by
        default, since their content is usually different."""
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        header = self._family_header(model.family_id)
        result = []
        released_by_layout = {}
        for checksheet_type in self.env['qc.checksheet.type'].browse(type_ids):
            # One search per layout, not per Type: Types sharing a layout share their candidates.
            layout = checksheet_type.layout
            if layout not in released_by_layout:
                released_by_layout[layout] = self.search(
                    [('state', '=', 'released'), ('checksheet_type', '=', layout), ('model_id', '!=', model.id)],
                    order='approved_date desc, id desc', limit=COPY_SOURCE_LIMIT)
            released = released_by_layout[layout]
            same_type = released.filtered(lambda s: s.type_id == checksheet_type)
            other_types = released - same_type
            options = [{
                'id': sheet.id,
                'label': sheet.display_name,
                'same_type': sheet.type_id == checksheet_type,
            } for sheet in same_type + other_types]
            result.append({
                'type_id': checksheet_type.id,
                'type_name': checksheet_type.name,
                'layout': checksheet_type.layout,
                'header': header,
                'source_id': same_type[:1].id,
                'options': options,
            })
        return result

    @api.model
    def model_create_sheets(self, model_id, rows):
        """All or nothing: one RPC is one transaction, so if any sheet fails, none
        is kept."""
        self._check_group(GROUP_AUTHOR)
        return [self.editor_create({
            'model_id': model_id,
            'type_id': row['type_id'],
            'header': row.get('header'),
            'source_id': row.get('source_id') or False,
        }) for row in rows]

    @api.model
    def editor_model_info(self, model_id):
        """A Model for the New page to start from, e.g. when opened from the Model QC page."""
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
        if not model:
            return False
        return {'id': model.id, 'name': model.display_name, 'model': model.family_id.name or ''}
