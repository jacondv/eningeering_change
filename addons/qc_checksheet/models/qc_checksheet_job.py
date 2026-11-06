from odoo import _, api, models
from odoo.exceptions import UserError

from .qc_checksheet import GROUP_AUTHOR
from .qc_checksheet_editor import COPY_SOURCE_LIMIT


class QcChecksheet(models.Model):
    """Server side of the Job QC page (static/src/job): every check sheet of
    one Job, by Type, and creating the missing ones in one go."""
    _inherit = 'qc.checksheet'

    @api.model
    def _job_sheets_by_type(self, job):
        sheets = {}
        for sheet in self.search([('job_number', '=', job.id)]).sorted('revision'):
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
    def job_overview(self, job_id):
        # Job details through sudo: seeing a Job's sheets shouldn't need Project access.
        job = self.env['project.project'].sudo().browse(job_id).exists()
        if not job:
            raise UserError(_("This Job no longer exists."))
        sheets_by_type = self._job_sheets_by_type(job)
        # Archived Types still show the sheets the Job already has.
        types = self.env['qc.checksheet.type'].search([]) | self.env['qc.checksheet.type'].union(*sheets_by_type)
        types = types.filtered(lambda t: t.required or t in sheets_by_type).sorted(
            lambda t: (not t.required, t.sequence, t.name))
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
            })
        return {
            'id': job.id,
            'name': job.display_name,
            'model': job.model_id.name or '',
            'customer': job.partner_id.name or '',
            'serial': job.machine_serial or '',
            'released': sum(1 for row in rows if row['required'] and row['current'] and row['current']['state'] == 'released'),
            'required': sum(1 for row in rows if row['required']),
            'rows': rows,
            # A sheet needs the Job's Model, so without one there is nothing to create.
            'can_author': self.env.user.has_group(GROUP_AUTHOR) and bool(job.model_id),
        }

    @api.model
    def job_sheet_sources(self, job_id, type_ids):
        """For each Type to create: what it can be copied from, and the one picked
        by default - the latest Released sheet of the same Type, same Model
        first. Sheets of another Type with the same layout are offered too, but
        never picked by default, since their content is usually different."""
        job = self.env['project.project'].sudo().browse(job_id).exists()
        header = self._family_header(job.model_id.family_id)
        result = []
        released_by_layout = {}
        for checksheet_type in self.env['qc.checksheet.type'].browse(type_ids):
            # One search per layout, not per Type: Types sharing a layout share their candidates.
            layout = checksheet_type.layout
            if layout not in released_by_layout:
                released_by_layout[layout] = self.search(
                    [('state', '=', 'released'), ('checksheet_type', '=', layout)],
                    order='approved_date desc, id desc', limit=COPY_SOURCE_LIMIT)
            released = released_by_layout[layout]
            same_type = released.filtered(lambda s: s.type_id == checksheet_type).sorted(
                lambda s: s.machine_model != job.model_id.name)
            other_types = released - same_type
            options = [{
                'id': sheet.id,
                'label': sheet.display_name,
                'same_type': sheet.type_id == checksheet_type,
                'same_model': sheet.machine_model == job.model_id.name,
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
    def job_create_sheets(self, job_id, rows):
        """All or nothing: one RPC is one transaction, so if any sheet fails, none
        is kept."""
        self._check_group(GROUP_AUTHOR)
        return [self.editor_create({
            'job_id': job_id,
            'type_id': row['type_id'],
            'header': row.get('header'),
            'source_id': row.get('source_id') or False,
        }) for row in rows]
