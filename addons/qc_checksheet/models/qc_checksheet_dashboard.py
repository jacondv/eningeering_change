from datetime import timedelta

from odoo import _, api, fields, models
from odoo.fields import Domain

OVERDUE_DAYS_PARAM = 'qc_checksheet.review_overdue_days'
DEFAULT_OVERDUE_DAYS = 3
# Jobs still being built: the only ones the Dashboard watches.
OPEN_JOB_STATUSES = ['in_progress', 'on_hold']
LIST_LIMIT = 10
JOB_PAGE_SIZE = 10


class QcChecksheet(models.Model):
    """Server side of the QC Dashboard (static/src/dashboard): counts of the
    sheets the search bar selects, plus the open Jobs still waiting for one."""
    _inherit = 'qc.checksheet'

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
                    # Through sudo: the Model may be one the user can't read; its name is all we show.
                    key, label = value.id, value.sudo().display_name
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
            'by_model': breakdown('model_id'),
            'rev_changes': self._dashboard_changes(search_domain, now),
            'inspections': self._dashboard_inspections(search_domain),
            'waiting_jobs': len(self._dashboard_waiting_jobs(search_domain)),
            'waiting': [self._dashboard_row(sheet, now) for sheet in waiting],
            'released': [self._dashboard_row(sheet, now) for sheet in released],
        }

    @api.model
    def _dashboard_inspections(self, domain):
        """How many printed sheets of open Jobs still wait for their signed scan, and how many Jobs
        must be inspected again after a change of Revision. Counted on the Revision the Job prints now,
        which the search bar selects like it does for the By Job Number panel."""
        JobSheet = self.env['qc.job.checksheet']
        base = [('checksheet_id', 'any', list(domain or [])), ('job_status', 'in', OPEN_JOB_STATUSES)]
        return {
            'awaiting': JobSheet.search_count(base + [('inspection_state', '=', 'awaiting')]),
            'reinspection': JobSheet.search_count(base + [('inspection_state', '=', 'reinspection')]),
        }

    @api.model
    def _dashboard_changes(self, domain, now):
        """Revision changes waiting for an Approver, oldest first. Found through the
        Revision the Job prints now, which may be Superseded, so the search bar
        selects them like the By Job Number panel does."""
        Change = self.env['qc.job.checksheet.change']
        change_domain = [('state', '=', 'pending'), ('from_checksheet_id', 'in', self._search(list(domain or [])))]
        return {
            'total': Change.search_count(change_domain),
            'items': [{
                'id': change.id,
                # Through sudo: the Job may be one the user can't read; its name is all we show.
                'job_id': change.job_id.id,
                'job': change.job_id.sudo().display_name,
                'type_id': change.type_id.id,
                'type': change.type_id.name,
                'from_revision': change.from_revision,
                'to_revision': change.to_revision,
                'requested_by': change.requested_by_id.name or '',
                'waiting_days': (now - change.requested_date).days if change.requested_date else 0,
            } for change in Change.search(change_domain, order='requested_date asc, id asc', limit=LIST_LIMIT)],
        }

    @api.model
    def dashboard_jobs(self, domain=None, page=0, term=''):
        """One page of the Jobs behind the search bar, with the sheets each has
        printed. A Job is counted through the Revisions it pinned, Superseded
        ones included: a Job still on an old Revision is what you look for."""
        sheets = self._search(list(domain or []))
        job_domain = [('checksheet_id', 'in', sheets)]
        term = (term or '').strip()
        if term:
            job_domain.append(('job_id.name', 'ilike', term))
        # Job names through sudo: a Job the user can't read still shows by name.
        groups = self.env['qc.job.checksheet'].sudo()._read_group(job_domain, ['job_id'], ['__count'])
        # Newest Jobs first, as Job numbers grow.
        items = sorted(
            ({'key': job.id, 'label': job.display_name, 'count': count} for job, count in groups),
            key=lambda item: item['label'], reverse=True)
        page = max(int(page or 0), 0)
        # A search that shrank the list can leave the page past its end.
        page = min(page, max(len(items) - 1, 0) // JOB_PAGE_SIZE)
        return {
            'items': items[page * JOB_PAGE_SIZE:(page + 1) * JOB_PAGE_SIZE],
            'total': len(items),
            'page': page,
            'page_size': JOB_PAGE_SIZE,
            'max_count': max((item['count'] for item in items), default=0),
        }

    @api.model
    def _dashboard_row(self, sheet, now):
        submitted = sheet.submitted_date
        return {
            'id': sheet.id,
            'layout': sheet.checksheet_type,
            'reference': sheet.reference or '',
            'name': sheet.name or '',
            'model': sheet.model_id.sudo().display_name or '',
            'revision': sheet.revision,
            'submitted_by': sheet.submitted_by_id.name or '',
            'waiting_days': (now - submitted).days if submitted else 0,
            'approved_by': sheet.approved_by_id.name or '',
            'approved_date': fields.Date.to_string(sheet.approved_date) or '',
        }

    @api.model
    def _dashboard_job_domain(self, domain):
        """The open Jobs (In Progress or On Hold) the search bar selects: its
        conditions on the Model carry over to the Job's Model, the ones about
        the sheet itself (status, Type, Header...) don't, since a Job waiting
        for a sheet has no sheet to match them. Such a condition counts as true,
        so inside an OR it makes that branch select every open Job: the card
        then shows more Jobs than the search names, never fewer."""
        def to_job(condition):
            path = condition.field_expr.split('.')
            if path[0] == 'model_id':
                if len(path) > 1:
                    field = 'model_id.' + '.'.join(path[1:])
                elif isinstance(condition.value, str):
                    field = 'model_id.name'
                else:
                    field = 'model_id'
            elif path == ['machine_model']:
                field = 'model_id.name'
            else:
                return Domain.TRUE
            return Domain(field, condition.operator, condition.value)
        return (
            Domain('model_id', '!=', False)
            & Domain('last_update_status', 'in', OPEN_JOB_STATUSES)
            & Domain(domain or []).map_conditions(to_job)
        )

    @api.model
    def _dashboard_waiting_jobs(self, domain=None):
        """The open Jobs the search bar selects that can't print every required
        sheet yet: never printed, and nothing Released on their Model."""
        # The user's own rights, so the card counts exactly the Jobs its list
        # shows. On Hold Jobs are archived, hence active_test=False.
        jobs = self.env['project.project'].with_context(active_test=False).search(self._dashboard_job_domain(domain))
        return jobs._qc_waiting_for_sheets()

    @api.model
    def action_open_waiting_jobs(self, domain=None):
        """A click on a row opens the Job's QC page."""
        waiting = self._dashboard_waiting_jobs(domain)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Jobs waiting for sheets'),
            'res_model': 'project.project',
            'views': [[self.env.ref('qc_checksheet.view_project_qc_missing_list').id, 'list']],
            'domain': [('id', 'in', waiting.ids)],
            'context': {'active_test': False, 'create': False},
        }
