from odoo import api, fields, models

TASK_TYPE_SELECTION = [
    ('3d', '3D'),
    ('2d', '2D'),
    ('sch', 'Sch'),
    ('bom', 'BOM'),
    ('checklist', 'Checklist'),
    ('fem', 'FEM'),
    ('rnd', 'R&D'),
    ('train', 'Train'),
    ('prog', 'Prog'),
    ('hyd', 'Hyd'),
    ('mnf', 'M&F'),
    ('cal', 'Cal'),
    ('test', 'Test'),
    ('s_manual', 'S-Manual'),
    ('m_manual', 'M-Manual'),
    ('o_manual', 'O-Manual'),
]


class ProjectTask(models.Model):
    _inherit = 'project.task'

    task_type = fields.Selection(
        TASK_TYPE_SELECTION, string='Task Type', index=True, tracking=True)
