from odoo.tests.common import TransactionCase


class EquipmentModelCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env['equipment.model.category'].create({'name': 'Test Group 01', 'last_job_number': 264})
        cls.family = cls.env['equipment.model.family'].create({'name': 'TS100', 'category_id': cls.group.id})
        cls.model = cls.env['equipment.model'].create({'name': 'TS100-A', 'family_id': cls.family.id})

    def _job(self, name, model=None, **values):
        return self.env['project.project'].create({'name': name, 'model_id': (model or self.model).id, **values})
