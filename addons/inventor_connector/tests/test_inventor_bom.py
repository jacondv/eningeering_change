import json

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestInventorBom(TransactionCase):

    def test_bom_type_unique_code(self):
        self.env['inventor.bom.type'].create({
            'code': 'test_bom_type', 'name': 'Panel & Sticker', 'line_model': 'res.partner',
        })
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env['inventor.bom.type'].create({
                'code': 'test_bom_type', 'name': 'Duplicate', 'line_model': 'res.partner',
            })
            self.env.flush_all()

    def test_bom_unique_model_bom_type(self):
        self.env['inventor.bom'].create({'model': 'JSV6', 'bom_type': 'test_bom_type'})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env['inventor.bom'].create({'model': 'JSV6', 'bom_type': 'test_bom_type'})
            self.env.flush_all()

    def test_upsert_missing_model_or_bom_type_raises(self):
        with self.assertRaises(UserError):
            self.env['inventor.bom']._upsert_from_payload({'bom_type': 'test_bom_type', 'lines': []})
        with self.assertRaises(UserError):
            self.env['inventor.bom']._upsert_from_payload({'model': 'JSV6', 'lines': []})

    def test_upsert_missing_lines_raises(self):
        with self.assertRaises(UserError):
            self.env['inventor.bom']._upsert_from_payload({'model': 'JSV6', 'bom_type': 'test_bom_type'})

    def test_upsert_unknown_bom_type_raises(self):
        with self.assertRaises(UserError):
            self.env['inventor.bom']._upsert_from_payload({
                'model': 'JSV6', 'bom_type': 'not_registered', 'lines': [],
            })

    def test_display_name_shows_model_and_bom_type(self):
        bom = self.env['inventor.bom'].create({
            'model': 'JSV6', 'bom_type': 'test_bom_type', 'name': 'Sample',
        })
        self.assertEqual(bom.display_name, 'JSV6 - test_bom_type (Sample)')

    def test_plain_internal_user_cannot_create_bom(self):
        user = self.env['res.users'].create({
            'name': 'Plain User', 'login': 'plain_user_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['inventor.bom'].with_user(user).create({
                'model': 'JSV6', 'bom_type': 'test_bom_type',
            })

    def test_bom_manager_group_can_create_bom(self):
        user = self.env['res.users'].create({
            'name': 'BOM Manager User', 'login': 'bom_manager_user_test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('inventor_connector.group_inventor_bom_manager').id,
            ])],
        })
        bom = self.env['inventor.bom'].with_user(user).create({
            'model': 'JSV6', 'bom_type': 'test_bom_type',
        })
        self.assertTrue(bom)

    # Note: the "upsert creates then updates the header, and replaces lines
    # rather than duplicating them" round-trip is tested in qc_checksheet's
    # test suite (test_qc_checksheet_inventor_import.py), since exercising
    # _upsert_from_payload's line handling needs a real registered line
    # model with a bom_id field - this connector deliberately owns no
    # concrete line model itself.


@tagged('post_install', '-at_install')
class TestInventorBomController(HttpCase):

    def _set_api_key(self, key):
        self.env['ir.config_parameter'].sudo().set_param('inventor_connector.api_key', key)

    def test_missing_api_key_returns_401(self):
        self._set_api_key('secret123')
        response = self.url_open(
            '/api/inventor/bom', data=json.dumps({}), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 401)

    def test_wrong_api_key_returns_401(self):
        self._set_api_key('secret123')
        response = self.url_open(
            '/api/inventor/bom', data=json.dumps({}),
            headers={'Content-Type': 'application/json', 'X-API-Key': 'wrong'})
        self.assertEqual(response.status_code, 401)

    def test_unknown_bom_type_returns_400(self):
        self._set_api_key('secret123')
        payload = {'model': 'JSV6', 'bom_type': 'no_such_type', 'lines': []}
        response = self.url_open(
            '/api/inventor/bom', data=json.dumps(payload),
            headers={'Content-Type': 'application/json', 'X-API-Key': 'secret123'})
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_returns_400(self):
        self._set_api_key('secret123')
        response = self.url_open(
            '/api/inventor/bom', data='not json',
            headers={'Content-Type': 'application/json', 'X-API-Key': 'secret123'})
        self.assertEqual(response.status_code, 400)
