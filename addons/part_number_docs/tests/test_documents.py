import base64

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

PDF = b'%PDF-1.4\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
ROOT = 'OneDrive - MAAS Group Holdings'
SAMPLE_PATH = (
    r'C:\Users\Ann\%s\JACON ENGINEERING\11. Technical Data Sheet\13. Electrical\KLIXON_C_Series.pdf' % ROOT
)


def b64(content):
    return base64.b64encode(content)


@tagged('post_install', '-at_install')
class TestPartDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Doc = cls.env['pnd.document']
        groups = 'base.group_user,part_number_docs.group_pnd_'
        cls.viewer = new_test_user(cls.env, login='pnd_viewer', groups=groups + 'view')
        cls.editor = new_test_user(cls.env, login='pnd_editor', groups=groups + 'edit')
        cls.manager = new_test_user(cls.env, login='pnd_manager', groups=groups + 'manage')
        cls.nobody = new_test_user(cls.env, login='pnd_nobody', groups='base.group_user')
        Part = cls.env['part_number_manager.part_number']
        cls.vendor = cls.env['res.partner'].create({'name': 'Klixon Corp'})
        job = cls.env['project.project'].create({'name': 'Job 1'})
        cls.part_a = Part.create({
            'job_number': job.id, 'part_number': '13050001', 'short_description': 'Circuit breaker 10A',
            'vendor_id': cls.vendor.id, 'vendor_ref': 'KLX-10',
        })
        cls.part_b = Part.create({'job_number': job.id, 'part_number': '13050002', 'short_description': 'Contactor 24V'})

    def _doc(self, **vals):
        values = {'name': 'Doc', 'kind': 'note', 'note': '<p>hello</p>'}
        values.update(vals)
        return self.Doc.create(values)

    def _file_doc(self, content=PDF, **vals):
        return self._doc(kind='file', note=False, file=b64(content), file_name='a.pdf', **vals)

    # -- what a document holds ------------------------------------------

    def test_a_new_document_is_a_datasheet_by_default(self):
        self.assertEqual(self._doc().type_id, self.env.ref('part_number_docs.type_datasheet'))

    def test_only_pdf_and_images_are_accepted_whatever_the_name_says(self):
        self.assertEqual(self._file_doc(PDF).file_mimetype, 'application/pdf')
        self.assertEqual(self._file_doc(PNG, name='Image').file_mimetype, 'image/png')
        for content in (b'<html><script>alert(1)</script></html>', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'MZ\x90\x00'):
            with self.assertRaises(UserError):
                self._file_doc(content, name='Bad')

    def test_a_file_larger_than_the_limit_is_refused(self):
        self.env['pnd.config']._get().max_file_mb = 1
        with self.assertRaises(UserError):
            self._file_doc(PDF + b'0' * (1024 * 1024 + 1), name='Big')

    def test_a_link_must_be_a_web_address(self):
        self.assertTrue(self._doc(kind='link', note=False, link_url='https://x.sharepoint.com/a.pdf'))
        for bad in ('javascript:alert(1)', 'file:///C:/a.pdf', 'not a link', 'https://a b.com'):
            with self.assertRaises(UserError):
                self._doc(kind='link', note=False, link_url=bad, name='Bad')

    def test_a_path_is_kept_from_the_synchronised_folder_on(self):
        doc = self._doc(kind='path', note=False, rel_path=SAMPLE_PATH)
        self.assertEqual(doc.rel_path, r'JACON ENGINEERING\11. Technical Data Sheet\13. Electrical\KLIXON_C_Series.pdf')
        # as copied by Explorer (with quotes), with slashes, or already relative
        quoted = self._doc(kind='path', note=False, rel_path='"%s"' % SAMPLE_PATH, name='Q')
        self.assertEqual(quoted.rel_path, doc.rel_path)
        relative = self._doc(kind='path', note=False, rel_path='JACON ENGINEERING/a/b.pdf', name='R')
        self.assertEqual(relative.rel_path, r'JACON ENGINEERING\a\b.pdf')

    def test_a_path_outside_the_shared_folder_or_going_up_is_refused(self):
        for bad in (r'C:\Users\Ann\Documents\a.pdf', r'D:\data\a.pdf', r'JACON\..\..\a.pdf', '', r'\\server\share\a.pdf'):
            with self.assertRaises(UserError):
                self._doc(kind='path', note=False, rel_path=bad, name='Bad')

    def test_a_note_cannot_be_empty_and_a_kind_holds_only_its_own_content(self):
        with self.assertRaises(UserError):
            self._doc(kind='note', note='<p><br></p>', name='Empty')
        doc = self._file_doc()
        doc.write({'kind': 'link', 'link_url': 'https://example.com/a'})
        self.assertFalse(doc.file)
        self.assertFalse(doc.file_name)
        self.assertEqual(doc.dedupe_key, 'link:https://example.com/a')
        with self.assertRaises(UserError):
            doc.write({'kind': 'file'})  # no file given

    # -- the same document twice ----------------------------------------

    def test_the_same_file_is_noticed_whatever_it_is_called(self):
        first = self._file_doc(name='First', part_number_ids=[(6, 0, self.part_a.ids)])
        form = self.Doc.new({'name': 'Again', 'kind': 'file', 'file': b64(PDF), 'file_name': 'other.pdf'})
        self.assertEqual(form.duplicate_id, first)
        self.assertIn('First', form.duplicate_hint)
        self.assertIn('13050001', form.duplicate_hint)
        other = self.Doc.new({'name': 'Different', 'kind': 'file', 'file': b64(PDF + b'x'), 'file_name': 'o.pdf'})
        self.assertFalse(other.duplicate_id)

    def test_links_and_paths_are_compared_in_a_normal_form(self):
        link = self._doc(kind='link', note=False, link_url='https://X.com/Doc.pdf/?utm_source=a#top', name='L')
        again = self.Doc.new({'kind': 'link', 'link_url': 'https://x.com/doc.pdf'})
        self.assertEqual(again.duplicate_id, link)
        path = self._doc(kind='path', note=False, rel_path=SAMPLE_PATH, name='P')
        same = self.Doc.new({'kind': 'path', 'rel_path': SAMPLE_PATH.lower().replace('c:\\users\\ann', 'D:\\Users\\Bob')})
        # a path under another user's drive is the same file
        self.assertEqual(same.duplicate_id, path)

    def test_using_the_existing_one_moves_the_part_numbers_and_drops_the_copy(self):
        first = self._file_doc(name='First', part_number_ids=[(6, 0, self.part_a.ids)])
        copy = self._file_doc(name='Copy', part_number_ids=[(6, 0, self.part_b.ids)])
        copy.invalidate_recordset()
        action = copy.with_user(self.editor).action_use_existing()
        self.assertEqual(action['res_id'], first.id)
        self.assertEqual(first.part_number_ids, self.part_a | self.part_b)
        self.assertFalse(copy.exists())

    def test_merging_gives_the_kept_document_all_the_part_numbers(self):
        keep = self._file_doc(name='Keep', part_number_ids=[(6, 0, self.part_a.ids)])
        drop = self._doc(name='Drop', part_number_ids=[(6, 0, self.part_b.ids)], vendor_id=self.vendor.id)
        wizard = self.env['pnd.document.merge.wizard'].with_user(self.editor).create({
            'document_ids': [(6, 0, (keep | drop).ids)], 'keep_id': keep.id,
        })
        self.assertEqual(wizard.action_merge(), {'type': 'ir.actions.act_window_close'})  # stays where it was
        self.assertFalse(drop.exists())
        self.assertFalse(self.env['ir.attachment'].sudo().search([('res_model', '=', 'pnd.document'), ('res_id', '=', drop.id)]))
        self.assertEqual(keep.part_number_ids, self.part_a | self.part_b)
        self.assertEqual(keep.vendor_id, self.vendor)
        with self.assertRaises(UserError):
            self.env['pnd.document'].browse(keep.id).with_user(self.editor).action_open_merge()  # one is not enough

    # -- who may do what -------------------------------------------------

    def test_the_three_levels(self):
        doc = self._file_doc(name='Shared')
        self.assertEqual(doc.with_user(self.viewer).name, 'Shared')
        with self.assertRaises(AccessError):
            doc.with_user(self.viewer).write({'name': 'x'})
        with self.assertRaises(AccessError):
            self.Doc.with_user(self.viewer).create({'name': 'x', 'kind': 'note', 'note': '<p>a</p>'})
        doc.with_user(self.editor).write({'name': 'Changed'})
        doc.with_user(self.editor).action_archive()
        self.assertFalse(doc.active)
        with self.assertRaises(AccessError):
            doc.with_user(self.editor).unlink()
        doc.with_user(self.manager).unlink()
        self.assertFalse(doc.exists())

    def test_without_a_level_nothing_is_seen(self):
        doc = self._doc()
        with self.assertRaises(AccessError):
            doc.with_user(self.nobody).read(['name'])
        with self.assertRaises(AccessError):
            self.Doc.with_user(self.nobody).search_documents('')

    def test_only_a_manager_changes_the_types_and_the_settings(self):
        Type = self.env['pnd.document.type']
        with self.assertRaises(AccessError):
            Type.with_user(self.editor).create({'name': 'Mine'})
        self.assertTrue(Type.with_user(self.manager).create({'name': 'Mine'}))
        config = self.env['pnd.config']._get()
        with self.assertRaises(AccessError):
            config.with_user(self.editor).write({'max_file_mb': 5})
        config.with_user(self.manager).write({'max_file_mb': 5})

    def test_documents_of_a_part_are_linked_by_those_who_may_edit_documents_only(self):
        doc = self._doc()
        self.part_a.invalidate_recordset()
        pnm_user = new_test_user(
            self.env, login='pnd_pnm', groups='base.group_user,part_number_manager.group_pnm_user,part_number_docs.group_pnd_view')
        with self.assertRaises(AccessError):
            self.part_a.with_user(pnm_user).write({'pnd_document_ids': [(4, doc.id)]})
        both = new_test_user(
            self.env, login='pnd_both', groups='base.group_user,part_number_manager.group_pnm_user,part_number_docs.group_pnd_edit')
        self.part_a.with_user(both).write({'pnd_document_ids': [(4, doc.id)]})
        self.assertEqual(self.part_a.pnd_document_count, 1)

    def test_new_users_start_with_view_and_current_users_were_given_it(self):
        view = self.env.ref('part_number_docs.group_pnd_view')
        self.assertIn(view, self.env.ref('base.default_user_group').implied_ids)
        self.assertIn(view, self.env.ref('base.user_admin').group_ids)

    # -- searching -------------------------------------------------------

    def test_search_all_finds_by_part_number_vendor_title_and_device_name(self):
        doc = self._file_doc(name='KLIXON C Series', part_number_ids=[(6, 0, self.part_a.ids)])
        other = self._doc(name='Contactor manual', part_number_ids=[(6, 0, self.part_b.ids)])
        search = lambda query, scope='all', **filters: {  # noqa: E731
            row['id'] for row in self.Doc.with_user(self.viewer).search_documents(query, scope, filters)['rows']}
        self.assertEqual(search('13050001'), {doc.id})
        self.assertEqual(search('klixon'), {doc.id})  # title, and the vendor
        self.assertEqual(search('breaker'), {doc.id})  # the device's description
        self.assertEqual(search('KLX-10'), {doc.id})  # vendor part no.
        self.assertEqual(search('contactor 24v'), {other.id})  # every word, anywhere
        self.assertEqual(search('contactor breaker'), set())
        self.assertEqual(search('13050001', 'vendor'), set())  # a part number is not a vendor
        self.assertEqual(search('klixon', 'vendor'), {doc.id})
        self.assertEqual(search('13050002', 'part_number'), {other.id})
        self.assertEqual(search('', type_ids=[doc.type_id.id]), {doc.id, other.id})
        self.assertEqual(search('', kinds=['file']), {doc.id})
        self.assertEqual(search('', kinds=['file', 'note']), {doc.id, other.id})  # several: any of them
        manual = self.env.ref('part_number_docs.type_manual')
        other.type_id = manual
        self.assertEqual(search('', type_ids=[manual.id, doc.type_id.id]), {doc.id, other.id})
        self.assertEqual(search('', type_ids=[manual.id], kinds=['file']), set())  # filters narrow each other
        # The chips of the search box: each in its own scope, all of them (and the free text) have to match.
        by_chips = lambda *chips, query='': {  # noqa: E731
            row['id'] for row in self.Doc.with_user(self.viewer).search_documents(
                query, facets=[{'scope': scope, 'value': value} for scope, value in chips])['rows']}
        self.assertEqual(by_chips(('vendor', 'klixon')), {doc.id})
        self.assertEqual(by_chips(('vendor', 'klixon'), ('part_number', '13050002')), set())
        self.assertEqual(by_chips(('title', 'klixon'), ('part_number', '13050001')), {doc.id})
        self.assertEqual(by_chips(('vendor', 'klixon'), query='series'), {doc.id})
        self.assertEqual(by_chips(('nonsense', 'klixon')), {doc.id, other.id})  # an unknown chip is ignored

    def test_archived_documents_are_listed_only_when_asked_and_a_row_is_light(self):
        doc = self._file_doc(name='Old one')
        doc.action_archive()
        self.assertFalse(self.Doc.with_user(self.viewer).search_documents('Old')['rows'])
        rows = self.Doc.with_user(self.viewer).search_documents('Old', filters={'archived': True})['rows']
        self.assertEqual([row['id'] for row in rows], [doc.id])
        self.assertEqual(rows[0]['extension'], 'pdf')
        self.assertNotIn('file', rows[0])

    # -- opening a path --------------------------------------------------

    def test_a_path_becomes_the_link_sharepoint_gives(self):
        path = r'C:\Users\Ann\%s\JACON ENGINEERING\11. Technical Data Sheet\13. Electrical\1305-Circuit Protection\Circuit Breaker\22725_25A.pdf' % ROOT
        doc = self._doc(kind='path', note=False, rel_path=path, name='SP')
        inside = '%2Fsites%2FJaconEng%2FShared%20Documents%2F11%2E%20Technical%20Data%20Sheet%2F13%2E%20Electrical%2F1305%2DCircuit%20Protection%2FCircuit%20Breaker'
        self.assertEqual(
            doc._sharepoint_url(),
            'https://maasgroupholdings.sharepoint.com/:b:/r/sites/JaconEng/Shared%20Documents/Forms/AllItems.aspx?id='
            + inside + '%2F22725%5F25A%2Epdf&parent=' + inside,
        )
        self.assertEqual(doc.with_user(self.viewer).get_preview()['web_url'], doc._sharepoint_url())
        opened = doc.with_user(self.viewer).action_open()
        self.assertEqual((opened['type'], opened['url'], opened['target']), ('ir.actions.act_url', doc._sharepoint_url(), 'new'))
        other = self._doc(kind='path', note=False, rel_path=r'JACON ENGINEERING\a b\Drawing.dwg', name='SP2')
        self.assertIn('/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FJaconEng%2FShared%20Documents%2Fa%20b%2FDrawing%2Edwg', other._sharepoint_url())
        self.assertNotIn('/:', other._sharepoint_url())  # no kind letter for a file of another kind
        self.assertEqual(self._doc(kind='path', note=False, rel_path='file-in-root.pdf', name='SP3')._sharepoint_url(), '')
        self.env['pnd.config']._get().sharepoint_url = False
        self.assertEqual(doc._sharepoint_url(), '')

    def test_without_sharepoint_a_path_is_opened_by_copying_the_path_on_the_users_own_pc(self):
        self.env['pnd.config']._get().sharepoint_url = False
        doc = self._doc(kind='path', note=False, rel_path=SAMPLE_PATH, name='P')
        preview = doc.with_user(self.viewer).get_preview()
        self.assertFalse(preview['can_open'])  # the user has not said where OneDrive is
        self.assertTrue(preview['copy_text'].startswith('%USERPROFILE%\\' + ROOT + '\\JACON ENGINEERING\\'))
        notice = doc.with_user(self.viewer).action_open()
        self.assertEqual(notice['tag'], 'display_notification')
        self.Doc.with_user(self.viewer).set_my_windows_folder('C:\\Users\\Ann Lee')
        preview = doc.with_user(self.viewer).get_preview()
        self.assertTrue(preview['can_open'])
        expected = (
            'C:\\Users\\Ann Lee\\%s\\JACON ENGINEERING\\11. Technical Data Sheet\\13. Electrical\\KLIXON_C_Series.pdf' % ROOT
        )
        self.assertEqual(preview['copy_text'], expected)
        opened = doc.with_user(self.viewer).action_open()
        self.assertEqual(
            (opened['type'], opened['tag'], opened['params']['text']),
            ('ir.actions.client', 'part_number_docs.open_path', expected),
        )

    def test_the_open_button_of_a_list_opens_each_kind(self):
        file = self._file_doc(name='My file.pdf')
        action = file.with_user(self.viewer).action_open()
        self.assertEqual((action['type'], action['target']), ('ir.actions.act_url', 'new'))
        self.assertEqual(action['url'], '/web/content/pnd.document/%s/file/a.pdf' % file.id)
        link = self._doc(kind='link', note=False, link_url='https://example.com/a', name='L')
        self.assertEqual(link.with_user(self.viewer).action_open()['url'], 'https://example.com/a')
        note = self._doc(name='N')
        self.assertEqual(note.with_user(self.viewer).action_open()['res_id'], note.id)
        with self.assertRaises(AccessError):
            link.with_user(self.nobody).action_open()

    def test_a_search_costs_the_same_number_of_queries_for_5_or_30_documents(self):
        for number in range(30):
            self._file_doc(PDF + str(number).encode(), name='Many %s' % number,
                           part_number_ids=[(6, 0, (self.part_a | self.part_b).ids)])
        viewer_docs = self.Doc.with_user(self.viewer)

        def queries(limit):
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            result = viewer_docs.search_documents('many', limit=limit)
            return self.env.cr.sql_log_count - before, result

        few, small = queries(5)
        many, result = queries(30)
        self.assertEqual((len(small['rows']), len(result['rows'])), (5, 30))
        self.assertLessEqual(many, few + 1)  # no query per row
        self.assertEqual(result['total'], 30)
        self.assertEqual(result['rows'][0]['parts'], ['13050001', '13050002'])
        self.assertEqual(result['rows'][0]['part_count'], 2)
        # the next pages are not recounted
        self.assertIsNone(viewer_docs.search_documents('many', offset=10, limit=10)['total'])
        # a long paste is cut to the first words
        words = ' '.join(['many'] * 10 + ['zzzz'])  # the last word is beyond the limit: not looked for
        self.assertEqual(viewer_docs.search_documents(words)['total'], 30)

    def test_the_part_documents_count_comes_from_one_query(self):
        self._doc(part_number_ids=[(6, 0, self.part_a.ids)])
        parts = self.part_a | self.part_b
        parts.invalidate_recordset()
        self.assertEqual(parts.mapped('pnd_document_count'), [1, 0])

    def test_the_file_of_a_file_document_cannot_be_emptied(self):
        doc = self._file_doc(name='Keeps its file')
        with self.assertRaises(UserError):
            doc.write({'file': False})
        self.assertTrue(doc.file)
        self.assertTrue(doc.dedupe_key.startswith('file:'))

    def test_the_all_documents_menu_can_be_hidden_in_the_settings(self):
        menu = self.env.ref('part_number_docs.menu_pnd_list')
        self.assertTrue(menu.active)
        config = self.env['pnd.config']._get()
        config.with_user(self.manager).write({'show_all_documents_menu': False})
        self.assertFalse(menu.active)
        config.with_user(self.manager).write({'show_all_documents_menu': True})
        self.assertTrue(menu.active)

    def test_the_windows_folder_must_look_like_one(self):
        for bad in ('C:\\Windows', 'Users\\Ann', 'C:\\Users\\Ann\\Desktop', 'javascript:1'):
            with self.assertRaises(UserError):
                self.Doc.with_user(self.viewer).set_my_windows_folder(bad)
        self.assertEqual(self.Doc.with_user(self.viewer).set_my_windows_folder('C:\\Users\\Ann\\'), 'C:\\Users\\Ann')
        self.assertEqual(self.Doc.with_user(self.viewer).set_my_windows_folder(''), '')
