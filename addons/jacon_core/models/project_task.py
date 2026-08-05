from odoo import api, fields, models

TASK_TYPE_SELECTION = [
    ('3d', '3D'),
    ('2d', '2D'),
    ('sch', 'Sch'),
    ('bom', 'BOM'),
    ('checklist', 'Checklist'),
    ('doc', 'Doc'),
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

    # Default to the creating user - core only does this when created from
    # a "My Tasks" personal-stage context, not from a Project's Tasks list.
    user_ids = fields.Many2many(default=lambda self: self.env.user.ids)

    task_type = fields.Selection(
        TASK_TYPE_SELECTION, string='Task Type', index=True, tracking=True)

    evidence_ids = fields.One2many(
        'engineering.change.action.evidence', 'task_id', string='Evidence')
    evidence_count = fields.Integer(compute='_compute_evidence_count')

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for rec in self:
            rec.evidence_count = len(rec.evidence_ids)
