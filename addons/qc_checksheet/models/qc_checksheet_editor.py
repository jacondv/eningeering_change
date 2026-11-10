from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from .qc_checksheet import GROUP_APPROVER, GROUP_AUTHOR

EMPTY_HTML = '<p><br></p>'
MODEL_SEARCH_LIMIT = 20
COPY_SOURCE_LIMIT = 50
USER_NAME_LIMIT = 500


class QcChecksheet(models.Model):
    """Server side of the Check Sheet Editor page (static/src/editor). The page
    edits a whole sheet in the browser and sends it back at once on Save, so
    editor_save() works out what changed. Everything goes through the normal
    ORM as the current user, so access rights and the Draft lock still apply.
    """
    _inherit = 'qc.checksheet'

    # Bumped on every Save, so a page left open can't overwrite a newer Save.
    editor_version = fields.Integer(default=1, readonly=True, copy=False)

    def action_open_editor(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'qc_checksheet.editor',
            'name': self.display_name,
            'context': {'active_id': self.id},
        }

    def action_open_default(self):
        """A row of the list: a standard sheet opens on the editor, where it is read and written;
        a Panel & Sticker one on its form, which is where that layout is edited."""
        self.ensure_one()
        if self.checksheet_type == 'standard':
            return self.action_open_editor()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'views': [(False, 'form')],
        }

    # Loading

    def editor_load(self):
        self.ensure_one()
        user = self.env.user
        revisions = self.root_id.revision_ids.sorted('revision')
        rev_sheets = {rev.revision: rev.id for rev in revisions}
        state_labels = dict(self._fields['state'].selection)
        return {
            'id': self.id,
            'number': self.reference or '',
            'name': self.name or '',
            'model_id': self.model_id.id,
            'family': self.model_id.sudo().family_id.name or '',
            'job_count': self.sheet_job_count,
            # The other Models that print this sheet instead of having one of their own.
            'shared_models': self.env['qc.checksheet.share']._users_of(self.model_id, self.type_id).model_id.mapped('name'),
            'type_name': self.type_id.name or '',
            'layout': self.checksheet_type,
            'revision': self.revision,
            'state': self.state,
            'state_label': state_labels[self.state],
            'reject_reason': self.reject_reason or '',
            'version': self.editor_version,
            'model': self.machine_model or '',
            # Offered as a base to compare with: the copied lines kept its line keys.
            # Plain False when there is none: an empty recordset reaches the page as [], which is truthy.
            'source': {
                'id': self.copied_from_id.id,
                'label': self.copied_from_id.sudo()._editor_source_label(),
            } if self.copied_from_id else False,
            'latest_id': revisions[-1].id,
            'revisions': [{
                'id': rev.id,
                'revision': rev.revision,
                'state_label': state_labels[rev.state],
            } for rev in revisions],
            'groups': [{
                'id': group.id,
                'line_key': group.line_key,
                'name': group.name or '',
                'items': [{
                    'id': item.id,
                    'line_key': item.line_key,
                    'description': item.description or '',
                    'acceptance': item.acceptance or '',
                    'note': item.note or '',
                } for item in group.item_ids],
            } for group in self.group_ids],
            'positions': [{'id': line.id, 'position': line.position} for line in self.approval_ids],
            'history': [{
                'id': line.id,
                'rev': line.rev,
                'description': line.description or '',
                'date': fields.Date.to_string(line.date) or '',
                'created_by': line.created_by or '',
                'approved_by': line.approved_by or '',
                'show_in_report': line.show_in_report,
                'legacy': line.legacy,
                'sheet_id': rev_sheets.get(line.rev, False),
            } for line in self.history_ids],
            # Suggestions for Created By in the Revision History.
            'user_names': self._editor_user_names(),
            'can_author': user.has_group(GROUP_AUTHOR),
            'can_approve': user.has_group(GROUP_APPROVER),
        }

    @api.model
    def _editor_user_names(self):
        """Names of the people who can be a Revision's creator: the company's own users, not portal or public ones."""
        users = self.env['res.users'].sudo().search([('share', '=', False)], order='name', limit=USER_NAME_LIMIT)
        return users.mapped('name')

    def _editor_source_label(self):
        self.ensure_one()
        return _('Copied from %(number)s Rev %(rev)s', number=self.reference or self.name, rev=self.revision)

    # Saving

    def editor_save(self, payload):
        self.ensure_one()
        self._check_group(GROUP_AUTHOR)
        self._check_state('draft')
        if payload.get('version') != self.editor_version:
            raise UserError(_(
                "Someone else saved this check sheet after you opened it. "
                "Reload the page to see their changes."))
        if not (payload.get('name') or '').strip():
            raise UserError(_("Enter the Header."))

        group_ids = self._editor_save_groups(payload.get('groups', []))
        position_ids = self._editor_save_positions(payload.get('positions', []))
        self._editor_save_history(payload.get('history', []))
        self.write({'name': payload['name']})
        self.sudo().editor_version += 1
        return {'version': self.editor_version, 'groups': group_ids, 'positions': position_ids}

    @api.model
    def _editor_write_changed(self, record, vals):
        changed = {}
        for key, value in vals.items():
            current = record[key]
            if isinstance(current, models.BaseModel):
                current = current.id
            elif isinstance(record._fields[key], fields.Date):
                current = fields.Date.to_string(current)
            if (current or False) != (value or False):
                changed[key] = value
        if changed:
            record.write(changed)

    def _editor_save_groups(self, groups_data):
        """Returns the ids in the order they were sent, so the page can give
        rows it just added their real id."""
        Group = self.env['qc.checksheet.group']
        Item = self.env['qc.checksheet.item']
        own_groups = self.group_ids
        own_items = own_groups.item_ids
        sent_groups = {data['id'] for data in groups_data if data.get('id')}
        sent_items = {item['id'] for data in groups_data for item in data['items'] if item.get('id')}
        if sent_groups - set(own_groups.ids) or sent_items - set(own_items.ids):
            raise UserError(_("This content does not belong to this check sheet. Reload the page."))
        own_items.filtered(lambda item: item.id not in sent_items).unlink()

        saved = []
        for group_index, data in enumerate(groups_data):
            group_vals = {'name': data.get('name') or EMPTY_HTML, 'sequence': (group_index + 1) * 10}
            if data.get('id'):
                group = Group.browse(data['id'])
                self._editor_write_changed(group, group_vals)
            else:
                group = Group.create({**group_vals, 'checksheet_id': self.id})
            item_ids = []
            for item_index, item_data in enumerate(data['items']):
                item_vals = {
                    'group_id': group.id,
                    'sequence': (item_index + 1) * 10,
                    'description': item_data.get('description') or False,
                    'acceptance': item_data.get('acceptance') or False,
                    'note': item_data.get('note') or False,
                }
                if item_data.get('id'):
                    item = Item.browse(item_data['id'])
                    self._editor_write_changed(item, item_vals)
                else:
                    item = Item.create(item_vals)
                item_ids.append(item.id)
            saved.append({'id': group.id, 'item_ids': item_ids})
        # Last: a kept Item may have just been dragged out of a Group being deleted.
        own_groups.filtered(lambda group: group.id not in sent_groups).unlink()
        return saved

    def _editor_save_positions(self, positions_data):
        Approval = self.env['qc.checksheet.approval']
        own = self.approval_ids
        sent = {data['id'] for data in positions_data if data.get('id')}
        if sent - set(own.ids):
            raise UserError(_("This content does not belong to this check sheet. Reload the page."))
        own.filtered(lambda line: line.id not in sent).unlink()
        saved = []
        for index, data in enumerate(positions_data):
            position = (data.get('position') or '').strip()
            if not position:
                raise UserError(_("Enter a name for each Approval Position, or delete the empty one."))
            vals = {'position': position, 'sequence': (index + 1) * 10}
            if data.get('id'):
                line = Approval.browse(data['id'])
                self._editor_write_changed(line, vals)
            else:
                line = Approval.create({**vals, 'checksheet_id': self.id})
            saved.append(line.id)
        return saved

    def _editor_save_history(self, history_data):
        lines = {line.id: line for line in self.history_ids}
        for data in history_data:
            line = lines.get(data.get('id'))
            if not line:
                raise UserError(_("This content does not belong to this check sheet. Reload the page."))
            vals = {'show_in_report': bool(data.get('show_in_report'))}
            # The write guard only lets the current Revision's own row change these, and a row of a
            # Revision from before Odoo, which is typed in by hand, Approved By included.
            if line.legacy:
                vals['description'] = data.get('description') or False
                vals['date'] = data.get('date') or False
                vals['created_by'] = (data.get('created_by') or '').strip() or False
                vals['approved_by'] = (data.get('approved_by') or '').strip() or False
            elif line.rev == self.revision:
                vals['description'] = data.get('description') or False
                vals['date'] = data.get('date') or False
                # Left empty it goes back to the user saving, like a Revision's first value.
                vals['created_by'] = (data.get('created_by') or '').strip() or self.env.user.name
            self._editor_write_changed(line, vals)

    # Creating

    @api.model
    def editor_types(self):
        types = self.env['qc.checksheet.type'].search([])
        return [{'id': t.id, 'name': t.name, 'code': t.code, 'layout': t.layout} for t in types]

    @api.model
    def _model_option(self, model):
        return {'id': model.id, 'name': model.display_name, 'model': model.family_id.name or ''}

    @api.model
    def editor_search_models(self, term=''):
        """Read through sudo: this only offers the name, and writing sheets
        shouldn't need access to the Model list."""
        models_ = self.env['equipment.model'].sudo().search(
            [('name', 'ilike', term or '')], limit=MODEL_SEARCH_LIMIT, order='name')
        return [self._model_option(model) for model in models_]

    @api.model
    def editor_new_context(self, model_id, type_id, source_model_id=False):
        """What the New page shows once a Model and a Type are picked.
        source_model_id narrows the sheets offered to copy from to that one Model."""
        model = self.env['equipment.model'].sudo().browse(model_id or 0).exists()
        checksheet_type = self.env['qc.checksheet.type'].browse(type_id or 0).exists()
        result = {
            'number': '',
            'header': '',
            'model': model.name or '',
            'family': model.family_id.name or '',
            # On Hold, EOL and Cancelled Jobs are archived, and still count, like on the Model page.
            'job_count': self.env['project.project'].sudo().with_context(active_test=False).search_count(
                [('model_id', '=', model.id)]) if model else 0,
            'duplicate_id': False,
            'sources': [],
        }
        if model:
            result['header'] = self._family_header(model.family_id)
        if model and checksheet_type:
            result['number'] = self._generate_reference(checksheet_type, model)
            duplicate = self.search([('model_id', '=', model.id), ('type_id', '=', checksheet_type.id)], limit=1)
            result['duplicate_id'] = duplicate.id
        if checksheet_type:
            domain = [('state', '=', 'released'), ('type_id', '=', checksheet_type.id)]
            if source_model_id:
                domain.append(('model_id', '=', source_model_id))
            sources = self.search(domain, limit=COPY_SOURCE_LIMIT, order='create_date desc')
            # The closest content to start from first: a Model of the same Product Family.
            sources = sources.sorted(lambda sheet: not (
                model.family_id and sheet.sudo().model_id.family_id == model.family_id))
            result['sources'] = [{
                'id': sheet.id,
                'label': sheet.display_name,
                'header': sheet.name,
                'groups': len(sheet.group_ids),
                'items': sheet.item_count,
            } for sheet in sources]
        return result

    @api.model
    def editor_search_source_models(self, type_id, term=''):
        """Models with a Released sheet that a sheet of this Type could be copied from."""
        checksheet_type = self.env['qc.checksheet.type'].browse(type_id).exists()
        released = self._search([('state', '=', 'released'), ('type_id', '=', checksheet_type.id)])
        models_ = self.env['equipment.model'].sudo().with_context(active_test=False).search([
            ('id', 'in', released.subselect('model_id')),
            ('name', 'ilike', term or ''),
        ], limit=MODEL_SEARCH_LIMIT, order='name')
        return [self._model_option(model) for model in models_]

    @api.model
    def editor_create(self, vals):
        self._check_group(GROUP_AUTHOR)
        start = vals.get('start_rev') or 0
        self._check_start_revision(start, vals.get('model_id'), vals.get('type_id'))
        checksheet = self.create({
            'name': vals.get('header'),
            'type_id': vals.get('type_id'),
            'model_id': vals.get('model_id'),
        })
        source = self.browse(vals.get('source_id'))
        if not source and vals.get('source_model_id'):
            # A Model to copy from: its Released sheet of this Type.
            source = self.sudo().search([
                ('model_id', '=', vals['source_model_id']), ('type_id', '=', vals.get('type_id')),
                ('state', '=', 'released')], limit=1)
            if not source:
                raise UserError(_("That Model has no Released sheet of this Type to copy."))
        if source:
            checksheet._copy_content_from(source)
        elif checksheet.checksheet_type == 'standard':
            self.env['qc.checksheet.group'].create({
                'checksheet_id': checksheet.id,
                'name': EMPTY_HTML,
                'item_ids': [(0, 0, {})],
            })
        checksheet._start_at_revision(start)
        return {'id': checksheet.id, 'layout': checksheet.checksheet_type}

    def _check_content_complete(self):
        """Blank rows would print as blank rows, so they stop a Submit."""
        self.ensure_one()
        if self.checksheet_type != 'standard':
            return
        for group in self.group_ids:
            if not _html_has_content(group.name):
                raise UserError(_("Every Group needs a name."))
            for item in group.item_ids:
                if not _html_has_content(item.description):
                    raise UserError(_("Item %s has no Description.", item.item_number))


def _html_has_content(html):
    return bool(html2plaintext(html or '').strip()) or '<img' in (html or '')
