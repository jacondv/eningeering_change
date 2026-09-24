from odoo import fields, models


class EngineeringChangeImpactAnswerWizard(models.TransientModel):
    """Popped up by action_submit (see _open_impact_answer_wizard) instead of
    a plain UserError when the Impact Analysis questions (Risk Assessment
    tab) aren't complete enough to Submit - lets the user answer right here
    instead of hunting for the tab themselves. Selection options mirror
    engineering.change's own IMPACT_ANSWERS constant; kept as a literal here
    since a wizard field can't reference another model's class attribute.
    """
    _name = 'engineering.change.impact.answer.wizard'
    _description = 'Engineering Change - Answer Impact Analysis Questions'

    change_id = fields.Many2one('engineering.change', required=True)
    impact_negative = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Does this change have any negative impact to safety or compliance issues?',
        required=True)
    impact_cost_over_100 = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Does this change negatively impact cost greater than 100usd?')
    impact_lead_time_over_week = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Does this change negatively impact lead time greater than 1 week?')
    impact_circuit_change = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string='Does this change affect the circuit functionality or specifications?')

    def action_confirm(self):
        self.ensure_one()
        vals = {'impact_negative': self.impact_negative}
        if self.impact_negative == 'no':
            vals.update({
                'impact_cost_over_100': self.impact_cost_over_100,
                'impact_lead_time_over_week': self.impact_lead_time_over_week,
                'impact_circuit_change': self.impact_circuit_change,
            })
        self.change_id.write(vals)
        return self.change_id.action_submit()
