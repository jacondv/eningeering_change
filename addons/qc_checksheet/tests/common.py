from odoo.tests.common import TransactionCase


class QcChecksheetCase(TransactionCase):

    _job_counter = 0
    _model_counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.type_general = cls.env.ref('qc_checksheet.checksheet_type_general')
        cls.type_panel = cls.env.ref('qc_checksheet.checksheet_type_panel_sticker')
        cls.model_za90 = cls.env['equipment.model'].create({'name': 'ZA90'})

    def _create_job(self, name=None, model=None, **vals):
        # Job names must be unique (see jacon_core).
        QcChecksheetCase._job_counter += 1
        return self.env['project.project'].create({
            'name': name or f'J-TEST-{QcChecksheetCase._job_counter}',
            'model_id': (model or self.model_za90).id,
            **vals,
        })

    def _create_model(self, name=None, **vals):
        QcChecksheetCase._model_counter += 1
        return self.env['equipment.model'].create({
            'name': name or f'M-TEST-{QcChecksheetCase._model_counter}', **vals})

    def _create_checksheet(self, checksheet_type=None, model=None, **vals):
        checksheet_type = checksheet_type or self.type_general
        if model is None:
            # ZA90 first; a Model holds one sheet per Type, so later ones get a Model of their own.
            model = self.model_za90
            if self.env['qc.checksheet'].search_count(
                    [('model_id', '=', model.id), ('type_id', '=', checksheet_type.id)]):
                model = self._create_model()
        return self.env['qc.checksheet'].create({
            'name': 'Start Up Check Sheet',
            'type_id': checksheet_type.id,
            'model_id': model.id,
            **vals,
        })

    def _create_content(self, checksheet, description='Check oil level'):
        return self.env['qc.checksheet.group'].create({
            'checksheet_id': checksheet.id, 'name': 'Hydraulic System',
            'item_ids': [(0, 0, {'description': description, 'acceptance': 'No leak'})],
        })

    def _release(self, checksheet):
        """Skip the workflow, for tests that only need a Released source."""
        checksheet.write({'state': 'released'})
        return checksheet
