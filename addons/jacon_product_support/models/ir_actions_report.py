from odoo import models
from odoo.tools.pdf import merge_pdf

EC_WITH_SERVICE_REPORT = 'jacon_product_support.action_report_ec_with_service_report'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """"Engineering Change + Service Report": the EC report followed by its
        linked request's Service Report, each rendered on its own and merged.

        Printing several ECs at once gives the ECs only. The Service Report is
        added regardless of the printing user's Product Support access.
        """
        report = self._get_report(report_ref)
        if report != self.env.ref(EC_WITH_SERVICE_REPORT, raise_if_not_found=False):
            return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

        ec_pdf, report_type = self._render_qweb_pdf(
            'engineering_change.action_report_engineering_change', res_ids=res_ids, data=data)
        ids = [res_ids] if isinstance(res_ids, int) else res_ids or []
        if len(ids) != 1:
            return ec_pdf, report_type
        request = self.env['product.support.request'].sudo().search(
            [('ec_id', '=', ids[0])], limit=1)
        if not request:
            return ec_pdf, report_type
        service_pdf, _type = self.sudo()._render_qweb_pdf(
            'jacon_product_support.action_report_product_support', res_ids=request.ids)
        return merge_pdf([ec_pdf, service_pdf]), report_type
