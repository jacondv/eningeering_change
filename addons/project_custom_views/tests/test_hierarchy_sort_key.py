from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHierarchySortKey(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'Hierarchy'})
        cls.Task = cls.env['project.task'].with_context(default_project_id=cls.project.id)

    def _key(self, *tasks):
        return '/'.join(f'{task.id:010d}' for task in tasks)

    def test_key_follows_the_path_from_the_root(self):
        root = self.Task.create({'name': 'Root'})
        child = self.Task.create({'name': 'Child', 'parent_id': root.id})
        grandchild = self.Task.create({'name': 'Grandchild', 'parent_id': child.id})

        self.assertEqual(root.hierarchy_sort_key, self._key(root))
        self.assertEqual(grandchild.hierarchy_sort_key, self._key(root, child, grandchild))

    def test_moving_a_task_moves_its_whole_subtree(self):
        old_root = self.Task.create({'name': 'Old root'})
        new_root = self.Task.create({'name': 'New root'})
        child = self.Task.create({'name': 'Child', 'parent_id': old_root.id})
        grandchild = self.Task.create({'name': 'Grandchild', 'parent_id': child.id})

        child.parent_id = new_root

        self.assertEqual(grandchild.hierarchy_sort_key, self._key(new_root, child, grandchild))

    def test_sub_tasks_sit_right_under_their_parent(self):
        first = self.Task.create({'name': 'First'})
        second = self.Task.create({'name': 'Second'})
        # Created last, so sorting by id alone would put it after Second.
        child = self.Task.create({'name': 'Child of first', 'parent_id': first.id})

        tasks = self.Task.search([('project_id', '=', self.project.id)], order='hierarchy_sort_key')

        self.assertEqual(tasks.ids, [first.id, child.id, second.id])

    def test_ids_of_different_lengths_keep_children_with_their_parent(self):
        # The next task's id is the parent's with a digit added (146 -> 1461):
        # it must not land between the parent and its child, the reason this
        # key exists instead of sorting by parent_path, which does exactly
        # that under an en_US collation.
        parent = self.Task.create({'name': 'Parent'})
        child = self.Task.create({'name': 'Child', 'parent_id': parent.id})
        self.env.cr.execute("SELECT setval('project_task_id_seq', %s, false)", [parent.id * 10 + 1])
        longer_id = self.Task.create({'name': 'Longer id'})
        self.assertEqual(longer_id.id, parent.id * 10 + 1)

        tasks = self.Task.search([('project_id', '=', self.project.id)], order='hierarchy_sort_key')

        self.assertEqual(tasks.ids, [parent.id, child.id, longer_id.id])
