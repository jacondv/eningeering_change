from odoo import api, fields, models
from odoo.osv import expression

from .qc_checksheet import GROUP_AUTHOR

OVERDUE_DAYS_PARAM = 'qc_checksheet.review_overdue_days'
DEFAULT_OVERDUE_DAYS = 3
JOB_STATUSES = ['in_progress', 'on_hold', 'eol', 'cancelled']
PAGE_SIZE = 50
KPI_FILTERS = ('missing', 'waiting', 'draft', 'complete')


class QcChecksheet(models.Model):
    """Server side of the QC Dashboard page (static/src/dashboard): every Job
    against every Check Sheet Type, with what exists in each cell."""
    _inherit = 'qc.checksheet'

    def _overdue_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param(OVERDUE_DAYS_PARAM)
        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            return DEFAULT_OVERDUE_DAYS

    @api.model
    def _dashboard_cell(self, revisions, now):
        """The Revision in use, plus the newer one being prepared if any."""
        current = revisions.filtered(lambda s: s.state == 'released')[:1] or revisions[-1:]
        latest = revisions[-1:]
        waiting = latest if latest.state == 'review' else self.browse()
        submitted = waiting and (waiting.submitted_date or waiting.write_date)
        return {
            'id': current.id,
            'layout': current.checksheet_type,
            'revision': current.revision,
            'state': current.state,
            'next': {'id': latest.id, 'revision': latest.revision, 'state': latest.state} if latest != current else False,
            'waiting_days': (now - submitted).days if submitted else 0,
            'updated_by': latest.write_uid.name or '',
            'updated_on': fields.Datetime.to_string(latest.write_date) or '',
            'reason': latest.change_reason or '',
        }

    @api.model
    def dashboard_data(self, filters=None):
        filters = filters or {}
        statuses = [s for s in filters.get('statuses') or [] if s in JOB_STATUSES] or ['in_progress']
        # Only the Job details go through sudo; the sheets are read with the user's own rights.
        # EOL, On Hold and Cancelled Jobs are archived, hence active_test=False.
        Project = self.env['project.project'].sudo().with_context(active_test=False)
        domain = [('model_id', '!=', False), ('last_update_status', 'in', statuses)]
        term = (filters.get('search') or '').strip()
        if term:
            domain = expression.AND([domain, expression.OR([
                [('name', 'ilike', term)], [('model_id.name', 'ilike', term)], [('partner_id.name', 'ilike', term)],
            ])])
        jobs_any_model = Project.search(domain)
        if filters.get('model_id'):
            domain = expression.AND([domain, [('model_id', '=', filters['model_id'])]])
        jobs = Project.search(domain, order='name desc')

        sheets = self.search([('job_number', 'in', jobs.ids)]).sorted('revision')
        by_cell = {}
        for sheet in sheets:
            key = (sheet.job_number.id, sheet.type_id.id)
            by_cell[key] = by_cell.get(key, self.browse()) | sheet
        used_type_ids = {type_id for _job, type_id in by_cell}
        types = self.env['qc.checksheet.type'].search([]).filtered(
            lambda t: t.required or t.id in used_type_ids).sorted(lambda t: (not t.required, t.sequence, t.name))
        required = types.filtered('required')

        now = fields.Datetime.now()
        overdue_days = self._overdue_days()
        rows = []
        kpis = dict.fromkeys(KPI_FILTERS, 0)
        for job in jobs:
            cells = {}
            for checksheet_type in types:
                revisions = by_cell.get((job.id, checksheet_type.id))
                if revisions:
                    cells[checksheet_type.id] = self._dashboard_cell(revisions, now)
                else:
                    cells[checksheet_type.id] = {'state': 'missing' if checksheet_type.required else 'none'}
            states = [cell['state'] for cell in cells.values()]
            pending = [cell['next']['state'] for cell in cells.values() if cell.get('next')]
            released = sum(1 for t in required if cells[t.id]['state'] == 'released')
            flags = {
                'missing': 'missing' in states,
                'waiting': 'review' in states + pending,
                'draft': 'draft' in states + pending,
                'complete': released == len(required),
            }
            kpis['waiting'] += (states + pending).count('review')
            kpis['draft'] += (states + pending).count('draft')
            kpis['missing'] += flags['missing']
            kpis['complete'] += flags['complete']
            rows.append({
                'id': job.id,
                'name': job.display_name,
                'model': job.model_id.name or '',
                'customer': job.partner_id.name or '',
                'released': released,
                'cells': cells,
                'flags': flags,
            })

        kpi = filters.get('kpi')
        if kpi in KPI_FILTERS:
            rows = [row for row in rows if row['flags'][kpi]]
        if filters.get('sort') == 'done':
            rows.sort(key=lambda row: row['released'])
        offset = max(int(filters.get('offset') or 0), 0)
        return {
            'columns': [{'id': t.id, 'name': t.name, 'code': t.code, 'required': t.required} for t in types],
            'required': len(required),
            'rows': rows[offset:offset + PAGE_SIZE],
            'total': len(rows),
            'offset': offset,
            'page_size': PAGE_SIZE,
            'kpis': kpis,
            'models': sorted(
                ({'id': model.id, 'name': model.name} for model in jobs_any_model.model_id),
                key=lambda model: model['name']),
            'overdue_days': overdue_days,
            'can_author': self.env.user.has_group(GROUP_AUTHOR),
        }

    @api.model
    def editor_job_info(self, job_id):
        """A Job for the New page to start from, e.g. when opened from the Dashboard."""
        job = self.env['project.project'].sudo().browse(job_id).exists()
        # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
        if not job:
            return False
        return {'id': job.id, 'name': job.display_name, 'model': job.model_id.name or ''}
