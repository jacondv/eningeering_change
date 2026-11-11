from odoo.tests.common import tagged

from .common import EquipmentModelCase


@tagged('post_install', '-at_install')
class TestDashboard(EquipmentModelCase):

    def data(self):
        return self.env['equipment.model'].get_dashboard_data()

    def row(self, rows, record):
        return next(row for row in rows if row['id'] == record.id)

    def test_counts_per_group_family_and_model(self):
        self._job('TS100-265')
        self._job('TS100-266')
        data = self.data()
        self.assertEqual(self.row(data['models'], self.model)['jobs'], 2)
        self.assertEqual(self.row(data['families'], self.family)['jobs'], 2)
        self.assertEqual(self.row(data['groups'], self.group)['jobs'], 2)
        self.assertEqual(self.row(data['groups'], self.group)['last_job_number'], 266)

    def test_a_model_takes_its_parents_family_as_job_names_do(self):
        child = self.env['equipment.model'].create({'name': 'TS100-A-1', 'parent_id': self.model.id})
        self._job('TS100-265', model=child)
        data = self.data()
        row = self.row(data['models'], child)
        self.assertEqual((row['family_id'], row['group_id'], row['jobs']), (self.family.id, self.group.id, 1))
        self.assertEqual(self.row(data['families'], self.family)['models'], 2)
        self.assertEqual(self.row(data['groups'], self.group)['jobs'], 1)

    def test_models_without_any_family_are_reachable_under_id_0(self):
        orphan = self.env['equipment.model'].create({'name': 'Orphan'})
        self._job('Orphan job', model=orphan)
        data = self.data()
        unassigned = self.row(data['families'], self.env['equipment.model.family'].browse(0))
        self.assertEqual((unassigned['models'], unassigned['jobs']), (1, 1))
        self.assertEqual(self.row(data['models'], orphan)['family_id'], 0)

    def test_no_unassigned_row_when_every_model_has_a_family(self):
        self.assertFalse([row for row in self.data()['families'] if row['id'] == 0])

    def test_templates_are_not_jobs(self):
        before = self.data()['totals']['jobs']
        self._job('TS100-300', is_template=True)
        self.assertEqual(self.data()['totals']['jobs'], before)

    def test_jobs_without_a_model(self):
        before = self.data()['jobs_without_model']
        self.env['project.project'].create({'name': 'No model job'})
        self.assertEqual(self.data()['jobs_without_model'], before + 1)
