from psycopg2 import IntegrityError

from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import EquipmentModelCase


@tagged('post_install', '-at_install')
class TestUniqueNames(EquipmentModelCase):

    def assertDuplicateRefused(self, model_name, values):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env[model_name].create(values)

    def test_group_names_are_unique_ignoring_case(self):
        self.assertDuplicateRefused('equipment.model.category', {'name': 'test group 01'})

    def test_family_names_are_unique_ignoring_case(self):
        self.assertDuplicateRefused('equipment.model.family', {'name': 'ts100', 'category_id': self.group.id})

    def test_model_names_are_unique_ignoring_case(self):
        self.assertDuplicateRefused('equipment.model', {'name': 'ts100-a'})

    def test_archived_names_are_taken_too(self):
        self.model.active = False
        self.assertDuplicateRefused('equipment.model', {'name': 'TS100-A'})
