from odoo import _, api, models
from odoo.exceptions import UserError

from .qc_checksheet import GROUP_AUTHOR, GROUP_USER
from .qc_checksheet_change import RUNNING_CHANGE_EXCLUDED_STATES
from .qc_checksheet_editor import COPY_SOURCE_LIMIT, MODEL_SEARCH_LIMIT


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
        Share = self.env['qc.checksheet.share']
        sheets_by_type = self._model_sheets_by_type(model)
        # A Type the Model uses another Model's sheet of shows that sheet.
        owner_of = {type_id: owner for (_model_id, type_id), owner in Share._owners(model).items()}
        for type_id, owner in owner_of.items():
            checksheet_type = self.env['qc.checksheet.type'].browse(type_id)
            sheets_by_type[checksheet_type] = self.search(
                [('model_id', '=', owner.id), ('type_id', '=', type_id)]).sorted('revision')
        users_by_type = {}
        for share in Share._users_of(model):
            users_by_type.setdefault(share.type_id.id, []).append(share.model_id.name)
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
        # The Jobs of this Model on a sheet it uses from another Model are counted by their own Model.
        shared_jobs = dict(JobSheet._read_group(
            [('job_id.model_id', '=', model.id), ('type_id', 'in', list(owner_of))],
            ['type_id'], ['job_id:count_distinct'])) if owner_of else {}
        shared_old = dict(JobSheet._read_group(
            [('job_id.model_id', '=', model.id), ('type_id', 'in', list(owner_of)),
             ('checksheet_id.state', '=', 'superseded')],
            ['type_id'], ['job_id:count_distinct'])) if owner_of else {}
        rows = []
        for checksheet_type in types:
            revisions = sheets_by_type.get(checksheet_type, self.browse())
            # The Revision in use; before any Release, the only one there is.
            current = revisions.filtered(lambda s: s.state == 'released')[:1] or revisions[-1:]
            latest = revisions[-1:]
            owner = owner_of.get(checksheet_type.id)
            rows.append({
                # The Model whose sheet this is, when it is another Model's.
                'shared_from': {'model_id': owner.id, 'name': owner.name} if owner else False,
                'shared_with': users_by_type.get(checksheet_type.id, []),
                'same_as': self._same_sheet_models(model, checksheet_type, current) if current and not owner else [],
                'type_id': checksheet_type.id,
                'type_name': checksheet_type.name,
                'required': checksheet_type.required,
                'layout': checksheet_type.layout,
                'number': current.reference or '',
                'header': current.name or '',
                # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
                'current': self._sheet_summary(current) if current else False,
                'next': self._sheet_summary(latest) if latest != current else False,
                'jobs': (shared_jobs if owner else jobs_by_type).get(checksheet_type, 0),
                'old_jobs': (shared_old if owner else old_by_type).get(checksheet_type, 0),
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
            'can_share': self.env.user.has_group(GROUP_USER),
        }

    @api.model
    def _same_sheet_models(self, model, checksheet_type, current):
        """The other Models whose current Released sheet of this Type prints exactly like this Model's: the ones
        it could be merged into. Only when it is a Released sheet nobody else uses."""
        if current.state != 'released' or self.env['qc.checksheet.share']._users_of(model, checksheet_type):
            return []
        candidates = self.sudo().search([
            ('type_id', '=', checksheet_type.id), ('state', '=', 'released'), ('model_id', '!=', model.id),
        ], limit=COPY_SOURCE_LIMIT)
        # A cheap look first (same numbers of Groups and Items), the full fingerprint only for those.
        shape = (len(current.group_ids), current.item_count, len(current.panel_line_ids))
        candidates = candidates.filtered(
            lambda sheet: (len(sheet.group_ids), sheet.item_count, len(sheet.panel_line_ids)) == shape)
        if not candidates:
            return []
        signature = current.sudo()._content_signature()
        same = candidates.filtered(lambda sheet: sheet._content_signature() == signature)
        # The Model whose name this one extends first (JSV6-EMU-A for JSV6-EMU-A-068), then the longest name.
        name = model.name or ''

        def extends(other):
            other_name = other.model_id.name or ''
            return bool(other_name) and name.startswith(other_name) and name[len(other_name):len(other_name) + 1] in '-_ /.'

        return [{'model_id': sheet.model_id.id, 'name': sheet.model_id.name} for sheet in same.sorted(
            lambda sheet: (not extends(sheet), -len(sheet.model_id.name or ''), sheet.id))]

    @api.model
    def model_sheet_sources(self, model_id, type_ids):
        """For each Type to set up: the Header to start with, and the Model whose sheet this one most likely uses
        (the one whose name this extends, JSV6-EMU-A for JSV6-EMU-A-068), if it has one."""
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        header = self._family_header(model.family_id)
        Share = self.env['qc.checksheet.share']
        result = []
        for checksheet_type in self.env['qc.checksheet.type'].browse(type_ids):
            suggested = Share._suggest_source(model, checksheet_type)
            result.append({
                'type_id': checksheet_type.id,
                'type_name': checksheet_type.name,
                'layout': checksheet_type.layout,
                'header': header,
                'share_model': self._model_option(suggested) if suggested else False,
            })
        return result

    @api.model
    def model_copy_sources(self, type_id, model_id, term=''):
        """The Models a new sheet of this Type can be copied from: those with a Released one. The same Type only:
        a sheet of another Type is never a starting point, whatever it looks like."""
        self._check_group(GROUP_USER)
        released = self.sudo()._search([('state', '=', 'released'), ('type_id', '=', type_id), ('model_id', '!=', model_id)])
        models_ = self.env['equipment.model'].sudo().with_context(active_test=False).search([
            ('id', 'in', released.subselect('model_id')), ('name', 'ilike', term or '')],
            limit=MODEL_SEARCH_LIMIT, order='name')
        return [self._model_option(model) for model in models_]

    @api.model
    def model_share_sources(self, type_id, model_id, term=''):
        """The Models whose sheet of this Type another Model can use: those that have one of their own."""
        self._check_group(GROUP_USER)
        sharing = self.env['qc.checksheet.share'].sudo().search([('type_id', '=', type_id)]).model_id
        with_sheet = self.sudo().search([('type_id', '=', type_id)]).model_id
        models_ = self.env['equipment.model'].sudo().with_context(active_test=False).search([
            ('id', 'in', (with_sheet - sharing - self.env['equipment.model'].browse(model_id)).ids),
            ('name', 'ilike', term or '')], limit=MODEL_SEARCH_LIMIT, order='name')
        return [self._model_option(model) for model in models_]

    @api.model
    def model_create_sheets(self, model_id, rows):
        """All or nothing: one RPC is one transaction, so if any sheet fails, none
        is kept."""
        # Using another Model's sheet is for anyone who can view; writing a sheet needs an Author.
        self._check_group(GROUP_USER if all(row.get('share_model_id') for row in rows) else GROUP_AUTHOR)
        created = []
        for row in rows:
            if row.get('share_model_id'):
                self.model_share(model_id, row['type_id'], row['share_model_id'])
                # No sheet was written: nothing to open.
                created.append({'id': False, 'layout': False, 'shared': True})
            else:
                created.append(self.editor_create({
                    'model_id': model_id,
                    'type_id': row['type_id'],
                    'header': row.get('header'),
                    'source_model_id': row.get('source_model_id') or False,
                    'start_rev': row.get('start_rev') or 0,
                }))
        return created

    # Sharing a sheet between Models (see qc.checksheet.share)

    @api.model
    def model_share(self, model_id, type_id, source_model_id):
        """Make a Model use another Model's sheet of a Type, or use a different one than before."""
        self._check_group(GROUP_USER)
        Share = self.env['qc.checksheet.share'].sudo()
        existing = Share.search([('model_id', '=', model_id), ('type_id', '=', type_id)])
        existing.unlink()
        Share.create({'model_id': model_id, 'type_id': type_id, 'source_model_id': source_model_id})
        return True

    @api.model
    def model_delete_sheets(self, model_id, type_ids):
        """Take the sheets of these Types away from a Model, to set them up again: a sheet the Model uses from
        another Model loses only the link, the other Model's sheet stays; the Model's own sheet is deleted with
        all its Revisions, which only a sheet nothing depends on can be (no Job printed it, no other Model uses
        it), and by someone allowed to: a Draft by an Author, a Released one by a QC Administrator."""
        self._check_group(GROUP_USER)
        Share = self.env['qc.checksheet.share'].sudo()
        JobSheet = self.env['qc.job.checksheet'].sudo()
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        if not model:
            raise UserError(_("This Model no longer exists."))
        own_to_delete = self.browse()
        for checksheet_type in self.env['qc.checksheet.type'].browse(type_ids).exists():
            share = Share.search([('model_id', '=', model.id), ('type_id', '=', checksheet_type.id)])
            if share:
                share.unlink()
                continue
            sheets = self.sudo().search([('model_id', '=', model.id), ('type_id', '=', checksheet_type.id)])
            if not sheets:
                continue
            if Share._users_of(model, checksheet_type):
                raise UserError(_(
                    "Other Models use the %(type)s sheet of %(model)s. Take it away from them first.",
                    type=checksheet_type.name, model=model.name))
            jobs = JobSheet.search([('checksheet_id', 'in', sheets.ids)]).job_id
            if jobs:
                raise UserError(_(
                    "The %(type)s sheet of %(model)s was printed by %(count)s Job(s), such as %(job)s, so it can't be deleted.",
                    type=checksheet_type.name, model=model.name, count=len(jobs), job=jobs[0].name))
            own_to_delete |= sheets
        # With the user's own rights: who may delete which Revisions is decided by qc.checksheet itself.
        own_to_delete.sudo(False).unlink()
        return True

    @api.model
    def model_merge(self, model_id, type_id, source_model_id):
        """Replace a Model's own sheet by another Model's, when they print the same: the Jobs, scans and
        change requests on its Revisions move to the identical Revision of the other sheet, the Model's own
        sheet is deleted, and the Model uses the other from then on."""
        self._check_group(GROUP_AUTHOR)
        Sheet = self.sudo()
        own = Sheet.search([('model_id', '=', model_id), ('type_id', '=', type_id)])
        theirs = Sheet.search([('model_id', '=', source_model_id), ('type_id', '=', type_id)])
        model = self.env['equipment.model'].sudo().browse(model_id)
        if not own or not theirs:
            raise UserError(_("Both Models need a sheet of this Type to merge."))
        if own.filtered(lambda sheet: sheet.state in ('draft', 'review')):
            raise UserError(_("%s has a Revision still being written or reviewed. Finish or discard it first.", model.name))
        if self.env['qc.checksheet.share']._users_of(model, own.type_id):
            raise UserError(_("Other Models use the sheet of %s. Move them first.", model.name))
        if self.env['qc.checksheet.share'].sudo().search_count(
                [('model_id', '=', source_model_id), ('type_id', '=', type_id)]):
            raise UserError(_("That Model uses another Model's sheet itself. Pick the Model that owns it."))
        own_current = own.filtered(lambda sheet: sheet.state == 'released')[:1]
        their_current = theirs.filtered(lambda sheet: sheet.state == 'released')[:1]
        if not own_current or not their_current:
            raise UserError(_("Both sheets need a Released Revision to merge."))
        if own_current._content_signature() != their_current._content_signature():
            raise UserError(_("The two sheets don't print the same, so they can't be merged."))

        # Each Revision of the Model's sheet that something points at goes to an identical one of the other.
        theirs_by_signature = {}
        for sheet in theirs.filtered(lambda sheet: sheet.state in ('released', 'superseded')).sorted('revision'):
            theirs_by_signature.setdefault(sheet._content_signature(), []).append(sheet)
        JobSheet = self.env['qc.job.checksheet'].sudo()
        Scan = self.env['qc.job.checksheet.scan'].sudo()
        Change = self.env['qc.job.checksheet.change'].sudo()
        moved = {}
        for sheet in own:
            used = (
                JobSheet.search([('checksheet_id', '=', sheet.id)])
                | JobSheet.search([('reinspection_waived_id', '=', sheet.id)])
                | Scan.search([('checksheet_id', '=', sheet.id)]).job_sheet_id
                | Change.search(['|', ('from_checksheet_id', '=', sheet.id), ('to_checksheet_id', '=', sheet.id)]).job_sheet_id)
            if not used:
                continue
            matches = theirs_by_signature.get(sheet._content_signature(), [])
            same_number = [other for other in matches if other.revision == sheet.revision]
            target = (same_number or matches[-1:] or [None])[0]
            if not target:
                raise UserError(_(
                    "Rev %(rev)s of %(model)s is used by Jobs, and %(source)s has no Revision that prints the same.",
                    rev=sheet.revision, model=model.name, source=theirs[0].model_id.name))
            moved[sheet] = target
        for sheet, target in moved.items():
            for job_sheet in JobSheet.search([('checksheet_id', '=', sheet.id)]):
                job_sheet.checksheet_id = target
                job_sheet.message_post(body=_(
                    "The sheet of %(model)s was merged into that of %(source)s: this Job is now on %(rev)s.",
                    model=model.name, source=target.model_id.name, rev=target.display_name))
            JobSheet.search([('reinspection_waived_id', '=', sheet.id)]).write({'reinspection_waived_id': target.id})
            Scan.search([('checksheet_id', '=', sheet.id)]).write({'checksheet_id': target.id})
            Change.search([('from_checksheet_id', '=', sheet.id)]).write({'from_checksheet_id': target.id})
            Change.search([('to_checksheet_id', '=', sheet.id)]).write({'to_checksheet_id': target.id})
        own.unlink()
        self.env['qc.checksheet.share'].sudo().create({
            'model_id': model_id, 'type_id': type_id, 'source_model_id': source_model_id})
        return True

    @api.model
    def editor_model_info(self, model_id):
        """A Model for the New page to start from, e.g. when opened from the Model QC page."""
        model = self.env['equipment.model'].sudo().browse(model_id).exists()
        # Plain False, not an empty recordset: that reaches the page as [], which is truthy.
        if not model:
            return False
        return {'id': model.id, 'name': model.display_name, 'model': model.family_id.name or ''}
