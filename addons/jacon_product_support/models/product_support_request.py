from datetime import datetime

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

OPEN_STATES = ('draft',)
RESOLVED_STATES = ('resolved', 'closed')


class ProductSupportRequest(models.Model):
    _name = 'product.support.request'
    _description = 'Product Support Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_names_search = ['name', 'title']

    # Identification
    name = fields.Char(string='Request No', required=True, readonly=True, copy=False,
                       default='New', index=True)
    title = fields.Char(required=True, tracking=True)
    request_date = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    requester_id = fields.Many2one('res.users', string='Requester', tracking=True,
                                   default=lambda self: self.env.user)
    engineer_id = fields.Many2one('res.users', string='Engineer', tracking=True,
                                  default=lambda self: self.env.user)
    priority = fields.Selection([
        ('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Critical'),
    ], default='1', tracking=True)

    # Machine & customer
    job_id = fields.Many2one(
        'project.project', string='Job Number', required=True, index=True,
        ondelete='restrict', tracking=True,
        domain=[('is_template', '=', False), ('is_ec_project', '=', False),
                ('is_ps_project', '=', False)])
    partner_id = fields.Many2one(related='job_id.partner_id', string='Customer', store=True)
    site_id = fields.Many2one(related='job_id.site_id', store=True)
    model_id = fields.Many2one(related='job_id.model_id', store=True)
    hour_meter = fields.Float(string='Operating Hours', tracking=True)
    machine_location = fields.Char()
    warranty = fields.Selection([
        ('in', 'In Warranty'), ('out', 'Out of Warranty'),
    ], tracking=True)

    # Customer contact
    contact_id = fields.Many2one('res.partner', string='Contact', tracking=True)
    contact_company_id = fields.Many2one(related='contact_id.parent_id', string='Company')
    contact_function = fields.Char(related='contact_id.function', string='Job Position')
    contact_phone = fields.Char(related='contact_id.phone', string='Phone')
    contact_email = fields.Char(related='contact_id.email', string='Email')

    # Fault
    fault_category_id = fields.Many2one('product.support.fault.category', tracking=True)
    machine_status = fields.Selection([
        ('down', 'Machine Down'),
        ('limited', 'Operating with Limitation'),
        ('normal', 'Operating Normally'),
    ], tracking=True)
    description = fields.Html(required=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'product_support_request_attachment_rel', 'request_id', 'attachment_id',
        string='Attachments', copy=False)

    document_ids = fields.One2many(
        'product.support.document', 'request_id', string='Related Drawings')

    # Resolution
    diagnosis = fields.Html(string='Diagnosing',
                            help="Analysis data collected while working on the request.")
    root_cause = fields.Html()
    solution = fields.Html(string='Solution / Instruction')
    # A confirmation date on its own means the customer has confirmed.
    customer_confirmed_date = fields.Date(string='Confirmation Date', tracking=True, copy=False)
    customer_confirmation_note = fields.Html(
        string='Evidence', copy=False,
        help="Proof the customer confirmed the support is OK (email, message, photo...).")
    ec_id = fields.Many2one('engineering.change', string='ECN No.',
                            copy=False, ondelete='set null', tracking=True,
                            domain=[('support_request_ids', '=', False)])
    ec_state = fields.Selection(related='ec_id.state', string='EC Status')

    # Workflow
    state = fields.Selection([
        ('draft', 'Open'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('canceled', 'Cancelled'),
    ], default='draft', required=True, copy=False, index=True, tracking=True)
    resolved_date = fields.Datetime(compute='_compute_resolved_date', store=True, copy=False)
    closed_date = fields.Datetime(compute='_compute_closed_date', store=True, copy=False)
    resolution_hours = fields.Float(
        string='Resolution Time (h)', compute='_compute_resolution_hours', store=True,
        aggregator='avg')

    project_id = fields.Many2one('project.project', readonly=True, copy=False,
                                 ondelete='restrict', index=True)
    action_ids = fields.One2many('project.task', 'support_request_id', string='Actions')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This Request No already exists.')
    _ec_uniq = models.Constraint(
        'unique(ec_id)', 'This Engineering Change is already linked to another Support Request.')

    # ------------------------------------------------------------
    # Computes & constraints
    # ------------------------------------------------------------
    @api.depends('state')
    def _compute_resolved_date(self):
        for rec in self:
            if rec.state not in RESOLVED_STATES:
                rec.resolved_date = False
            elif not rec.resolved_date:
                rec.resolved_date = fields.Datetime.now()

    @api.depends('state')
    def _compute_closed_date(self):
        for rec in self:
            if rec.state != 'closed':
                rec.closed_date = False
            elif not rec.closed_date:
                rec.closed_date = fields.Datetime.now()

    @api.depends('request_date', 'resolved_date')
    def _compute_resolution_hours(self):
        for rec in self:
            if rec.request_date and rec.resolved_date:
                # max(): Request Date can be edited to after the resolution.
                rec.resolution_hours = max(
                    (rec.resolved_date - rec.request_date).total_seconds() / 3600, 0.0)
            else:
                rec.resolution_hours = 0.0

    @api.constrains('state', 'root_cause', 'solution')
    def _check_resolution_filled(self):
        for rec in self.filtered(lambda r: r.state in RESOLVED_STATES):
            missing = [
                rec._fields[fname].string for fname in ('root_cause', 'solution')
                if not html2plaintext(rec[fname] or '').strip()
            ]
            if missing:
                raise ValidationError(_(
                    "%(request)s cannot be Resolved/Closed until these are filled in: %(fields)s",
                    request=rec.name, fields=', '.join(missing)))

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self._next_request_no()
        records = super().create(vals_list)
        records._create_container_project()
        records._notify_new_request()
        records._sync_job_operating_hours()
        return records

    def write(self, vals):
        if 'active' in vals or vals.get('state') == 'canceled':
            self._check_is_manager()
        # Leaving Cancelled any other way than Unarchive must also bring the
        # request back out of Archive, or it would be "Open" but invisible.
        revived = self.browse()
        if vals.get('state', 'canceled') != 'canceled' and 'active' not in vals:
            revived = self.filtered(lambda r: r.state == 'canceled' and not r.active)
        result = super().write(vals)
        if revived:
            super(ProductSupportRequest, revived).write({'active': True})
        if {'hour_meter', 'job_id'} & vals.keys():
            self._sync_job_operating_hours()
        return result

    def _sync_job_operating_hours(self):
        """Raise the Job Number's Op. Hours to this request's reading when
        higher - never lowers it (an older request's reading is stale)."""
        for rec in self.filtered('job_id'):
            hours = int(rec.hour_meter)
            job = rec.job_id.sudo()  # support users needn't have write access to the Job
            if hours > job.op_hours:
                old_hours = job.op_hours
                job.op_hours = hours
                job.message_post(
                    body=Markup(_("Op. Hours updated from %(old)s to %(new)s by %(request)s")) % {
                        'old': old_hours, 'new': hours, 'request': rec._get_html_link()},
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )

    def _notify_new_request(self):
        """Tell the Support Engineer and their direct manager (hr.employee
        parent) about the new request, following it so later updates reach them too."""
        for rec in self:
            engineer = rec.engineer_id
            manager = engineer.sudo().employee_id.parent_id.user_id
            partners = (engineer | manager).partner_id
            if not partners:
                continue
            rec.message_subscribe(partner_ids=partners.ids)
            rec.message_post(
                body=_("New support request %(name)s assigned to %(engineer)s.",
                       name=rec.name, engineer=engineer.name or '-'),
                partner_ids=partners.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def unlink(self):
        if not self.env.context.get('delete_password_confirmed'):
            raise UserError(_(
                "Use Delete in the gear menu of the Request form - "
                "it asks for your password first."))
        self.check_access('unlink')
        projects = self.project_id
        tasks = self.with_context(active_test=False).action_ids.sudo()
        attachments = self.attachment_ids.sudo()
        # Timesheets block task deletion, and the project is ondelete=restrict
        # while still referenced - so clear bottom-up before the request itself.
        tasks.timesheet_ids.unlink()
        tasks.unlink()
        result = super().unlink()
        projects.sudo().with_context(project_delete_password_confirmed=True).unlink()
        attachments.unlink()
        return result

    def _next_request_no(self):
        """YYMMPSNN from one ir.sequence whose counter restarts every month.

        Odoo only auto-creates yearly date ranges, so this month's range is
        created here on first use. The advisory lock stops two concurrent
        first-of-the-month creates from both adding a range for the same month.
        """
        today = fields.Date.context_today(self)
        sequence = self.env.ref('jacon_product_support.seq_product_support_request').sudo()
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (sequence.id,))
        month_start = today.replace(day=1)
        if not sequence.date_range_ids.filtered(
                lambda r: r.date_from <= today <= r.date_to):
            sequence.date_range_ids = [(0, 0, {
                'date_from': month_start,
                'date_to': month_start + relativedelta(months=1, days=-1),
                'number_next': 1,
            })]
        return sequence.next_by_id(sequence_date=today)

    def _create_container_project(self):
        Project = self.env['project.project'].sudo()
        for rec in self:
            rec.project_id = Project.create({
                'name': rec.name,
                'is_ps_project': True,
                'privacy_visibility': 'employees',
            })
            # Actions added before the first save were created without a project.
            rec.action_ids.sudo().write({'project_id': rec.project_id.id})

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def _check_is_manager(self):
        if not self.env.su and not self.env.user.has_group('jacon_product_support.group_ps_manager'):
            raise UserError(_("Only a Product Support Manager can cancel, archive or unarchive a request."))

    def action_cancel(self):
        """Cancelled requests are archived straight away."""
        self.write({'state': 'canceled', 'active': False})

    def action_unarchive(self):
        result = super().action_unarchive()
        self.filtered(lambda r: r.state == 'canceled').state = 'draft'
        return result

    def action_delete_with_password(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Deletion'),
            'res_model': 'jacon.delete.password.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_redirect_action_xmlid': 'jacon_product_support.action_product_support_request',
            },
        }

    def action_create_engineering_change(self):
        self.ensure_one()
        if self.ec_id:
            raise UserError(_("This Request is already linked to %s.", self.ec_id.name))
        origin = Markup("<p>Raised from Product Support <b>%s</b></p>") % self.name
        self.ec_id = self.env['engineering.change'].create({
            'title': self.title[:100],
            'change_category': 'Product Support',
            'requester_id': self.requester_id.id,
            'background': origin,
            'description': origin,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'engineering.change',
            'res_id': self.ec_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------
    # Report
    # ------------------------------------------------------------
    def _report_date(self, value):
        if not value:
            return ''
        if isinstance(value, datetime):
            value = fields.Datetime.context_timestamp(self, value)
        return value.strftime('%d-%b-%Y')

    def _report_label(self, fname):
        return dict(self._fields[fname]._description_selection(self.env)).get(self[fname], '')

    def _report_info_sections(self):
        """Label/value sections for the Service Report, each a list of rows
        of two (label, value) pairs - printed as a 4-column grid. A None
        pair leaves that half of the row blank."""
        self.ensure_one()
        contact = self.contact_id
        confirmation = self._report_date(self.customer_confirmed_date) or _('Not confirmed')
        return [
            (_('General Information'), [
                ((_('Job Number'), self.job_id.name), (_('Customer'), self.partner_id.display_name)),
                ((_('Model'), self.model_id.display_name), (_('Site'), self.site_id.display_name)),
                ((_('Operating Hours'), f'{self.hour_meter:g}'), (_('Contact'), contact.name)),
                ((_('Warranty'), self._report_label('warranty')), (_('Phone'), contact.phone)),
                ((_('Machine Location'), self.machine_location), (_('Email'), contact.email)),
            ]),
            (_('Request Details'), [
                ((_('Request Date'), self._report_date(self.request_date)),
                 (_('Fault Category'), self.fault_category_id.name)),
                ((_('Requester'), self.requester_id.name),
                 (_('Machine Status'), self._report_label('machine_status'))),
                ((_('Engineer'), self.engineer_id.name),
                 (_('Priority'), self._report_label('priority'))),
            ]),
            (_('Closure'), [
                ((_('Resolved Date'), self._report_date(self.resolved_date)),
                 (_('Closed Date'), self._report_date(self.closed_date))),
                ((_('Customer Confirmation'), confirmation),
                 (_('ECN No.'), self.ec_id.name or '')),
                ((_('Status'), self._report_label('state')), None),
            ]),
        ]

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, domain=None):
        domain = list(domain or [])
        month_start = fields.Date.context_today(self).replace(day=1)

        def count(extra):
            return self.search_count(domain + extra)

        state_labels = dict(self._fields['state']._description_selection(self.env))

        def breakdown(groupby):
            field = self._fields[groupby]
            rows = self._read_group(domain, [groupby], ['__count'])
            items = []
            for value, total in rows:
                if field.type == 'selection':
                    key, label = value, dict(field._description_selection(self.env)).get(value)
                else:
                    key, label = value.id, value.display_name
                items.append({'key': key or False, 'label': label or _('Undefined'), 'count': total})
            return sorted(items, key=lambda i: -i['count'])

        avg_rows = self._read_group(domain + [('resolved_date', '!=', False)], [],
                                    ['resolution_hours:avg'])
        return {
            'total': count([]),
            'kpis': {
                'open': count([('state', 'in', OPEN_STATES)]),
                'down': count([('state', 'in', OPEN_STATES), ('machine_status', '=', 'down')]),
                'resolved': count([('state', '=', 'resolved')]),
                'closed_month': count([('state', '=', 'closed'), ('closed_date', '>=', month_start)]),
            },
            'avg_resolution_hours': round(avg_rows[0][0] or 0.0, 1),
            'by_state': breakdown('state'),
            'by_category': breakdown('fault_category_id'),
            'by_model': breakdown('model_id'),
            'by_customer': breakdown('partner_id'),
            'recent': [{
                'id': rec.id,
                'name': rec.name,
                'title': rec.title,
                'job': rec.job_id.display_name or '',
                'customer': rec.partner_id.display_name or '',
                'requester': rec.requester_id.name or '',
                'priority': int(rec.priority or 0),
                'state': state_labels[rec.state],
            } for rec in self.search(domain, limit=8)],
        }
