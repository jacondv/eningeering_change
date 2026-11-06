from odoo.tests.common import TransactionCase


class QcChecksheetCase(TransactionCase):

    _job_counter = 0

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

    def _create_checksheet(self, checksheet_type=None, job=None, **vals):
        # A Job holds one sheet per Type, so each call gets its own Job by default.
        return self.env['qc.checksheet'].create({
            'name': 'Start Up Check Sheet',
            'type_id': (checksheet_type or self.type_general).id,
            'job_number': (job or self._create_job()).id,
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
