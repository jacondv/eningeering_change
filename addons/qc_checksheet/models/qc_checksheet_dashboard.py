from datetime import timedelta

from odoo import _, api, fields, models
from odoo.fields import Domain

OVERDUE_DAYS_PARAM = 'qc_checksheet.review_overdue_days'
DEFAULT_OVERDUE_DAYS = 3
# Sheet fields that are really the Job's, and what they are on the Job.
JOB_FIELDS = {
    'job_status': 'last_update_status',
    'machine_model': 'model_id.name',
    'machine_serial': 'machine_serial',
    'engine_number': 'engine_serial',
    'customer': 'partner_id.name',
}
LIST_LIMIT = 10


class QcChecksheet(models.Model):
    """Server side of the QC Dashboard (static/src/dashboard): counts of the
    sheets the search bar selects, plus the Jobs still missing sheets."""
    _inherit = 'qc.checksheet'

    # Stored so the search bar can filter on it: the Job may be archived (On
    # Hold, EOL and Cancelled are), and searching through job_number would
    # then find nothing.
    job_status = fields.Selection(
        related='job_number.last_update_status', store=True, string='Job Status')

    def _overdue_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param(OVERDUE_DAYS_PARAM)
        try:
            return max(int(value), 1)
        except (TypeError, ValueError):
            return DEFAULT_OVERDUE_DAYS

    @api.model
    def get_dashboard_data(self, domain=None):
        search_domain = list(domain or [])
        # Superseded Revisions are history, never counted.
        domain = search_domain + [('state', '!=', 'superseded')]
        now = fields.Datetime.now()
        overdue_days = self._overdue_days()
        overdue_before = now - timedelta(days=overdue_days)

        # Every figure counts Revisions in use, exactly like the lists the
        # cards and bars open: a Released sheet with a Draft Revision counts twice.
        def breakdown(groupby):
            items = []
            for value, total in self._read_group(domain, [groupby], ['__count']):
                if isinstance(value, models.BaseModel):
                    key, label = value.id, value.display_name
                else:
                    key, label = value, value
                items.append({'key': key or False, 'label': label or _('Undefined'), 'count': total})
            items.sort(key=lambda item: -item['count'])
            return items

        state_labels = dict(self._fields['state']._description_selection(self.env))
        by_state = [
            {'key': value, 'label': state_labels[value], 'count': total}
            for value, total in self._read_group(domain, ['state'], ['__count'])
        ]
        by_state.sort(key=lambda item: list(state_labels).index(item['key']))
        by_state_count = {item['key']: item['count'] for item in by_state}

        waiting = self.search(domain + [('state', '=', 'review')], order='submitted_date asc, id asc', limit=LIST_LIMIT)
        released = self.search(
            domain + [('state', '=', 'released')], order='approved_date desc, id desc', limit=LIST_LIMIT)
        return {
            'total': sum(by_state_count.values()),
            'kpis': {
                'draft': by_state_count.get('draft', 0),
                'review': by_state_count.get('review', 0),
                'overdue': self.search_count(
                    domain + [('state', '=', 'review'), ('submitted_date', '<=', overdue_before)]),
                'released': by_state_count.get('released', 0),
            },
            'overdue_days': overdue_days,
            'overdue_before': fields.Datetime.to_string(overdue_before),
            'by_state': by_state,
            'by_type': breakdown('type_id'),
            'by_model': breakdown('machine_model'),
            'jobs': self._dashboard_jobs(search_domain),
            'waiting': [self._dashboard_row(sheet, now) for sheet in waiting],
            'released': [self._dashboard_row(sheet, now) for sheet in released],
        }

    @api.model
    def _dashboard_row(self, sheet, now):
        submitted = sheet.submitted_date
        return {
            'id': sheet.id,
            'layout': sheet.checksheet_type,
            'reference': sheet.reference or '',
            'name': sheet.name or '',
            'job': sheet.job_number.sudo().display_name or '',
            'revision': sheet.revision,
            'submitted_by': sheet.submitted_by_id.name or '',
            'waiting_days': (now - submitted).days if submitted else 0,
            'approved_by': sheet.approved_by_id.name or '',
            'approved_date': fields.Date.to_string(sheet.approved_date) or '',
        }

    @api.model
    def _dashboard_job_domain(self, domain):
        """The search bar's sheet domain, as a domain on Jobs: the conditions
        about the Job (status, number, Model, customer, serial) carry over,
        the ones about the sheet itself (status, Type, Header...) don't, since
        a Job missing sheets has no sheet to match them."""
        def to_job(condition):
            path = condition.field_expr.split('.')
            if path[0] == 'job_number':
                if len(path) > 1:
                    field = '.'.join(path[1:])
                elif isinstance(condition.value, str):
                    field = 'name'
                else:
                    field = 'id'
            elif path[0] in JOB_FIELDS and len(path) == 1:
                field = JOB_FIELDS[path[0]]
            else:
                return Domain.TRUE
            return Domain(field, condition.operator, condition.value)
        return Domain('model_id', '!=', False) & Domain(domain or []).map_conditions(to_job)

    @api.model
    def _dashboard_job_sets(self, domain=None):
        """The Jobs the search bar selects, against the required Check Sheet
        Types: (all, missing a sheet, every one Released)."""
        # The user's own rights, so "Jobs missing sheets" counts exactly the Jobs
        # its list will show. On Hold, EOL and Cancelled Jobs are archived, hence active_test=False.
        jobs = self.env['project.project'].with_context(active_test=False).search(self._dashboard_job_domain(domain))
        required = self.env['qc.checksheet.type'].search([('required', '=', True)])
        job_domain = [('job_number', 'in', jobs.ids), ('type_id', 'in', required.ids)]
        existing = dict(self.sudo()._read_group(job_domain, ['job_number'], ['type_id:count_distinct']))
        released = dict(self.sudo()._read_group(
            job_domain + [('state', '=', 'released')], ['job_number'], ['type_id:count_distinct']))
        missing = jobs.filtered(lambda job: existing.get(job, 0) < len(required))
        complete = jobs.filtered(lambda job: released.get(job, 0) == len(required))
        return jobs, missing, complete

    @api.model
    def _dashboard_jobs(self, domain=None):
        jobs, missing, complete = self._dashboard_job_sets(domain)
        return {'total': len(jobs), 'missing': len(missing), 'complete': len(complete)}

    @api.model
    def action_open_missing_jobs(self, domain=None):
        """The Jobs the search bar selects that still miss a required sheet; a
        click opens the Job's QC page."""
        missing = self._dashboard_job_sets(domain)[1]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Jobs missing sheets'),
            'res_model': 'project.project',
            'views': [[self.env.ref('qc_checksheet.view_project_qc_missing_list').id, 'list']],
            'domain': [('id', 'in', missing.ids)],
            'context': {'active_test': False, 'create': False},
        }

    @api.model
    def editor_job_info(self, job_id):
        """A Job for the New page to start from, e.g. when opened from the Job QC page."""
        job = self.env['project.project'].sudo().browse(job_id).exists()
        # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
        if not job:
            return False
        return {'id': job.id, 'name': job.display_name, 'model': job.model_id.name or ''}
