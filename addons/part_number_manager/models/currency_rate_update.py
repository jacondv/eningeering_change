import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Free, no-key-required FX feed - {base} is a 3-letter currency code, the
# response's "rates" dict is keyed the same way Odoo's own res.currency.rate
# expects: 1 unit of `base` = rates[X] units of X. Calling it with base =
# the company's own currency therefore maps straight onto
# res.currency.rate.rate (defined relative to the company currency) with no
# extra math.
RATE_API_URL = 'https://open.er-api.com/v6/latest/{base}'
RATE_API_TIMEOUT = 15


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    def write(self, vals):
        result = super().write(vals)
        if 'active' in vals:
            # A newly-enabled Currency otherwise shows a misleading "1"
            # Current Rate until tomorrow's cron run - refresh right away.
            # Also covers disabling one, in case the company's base
            # currency itself was the one toggled. Triggered via the cron
            # (runs in the cron worker moments later) rather than called
            # inline, since the refresh itself does a blocking HTTP call
            # per company and would otherwise stall this write's request.
            self.env.ref('part_number_manager.ir_cron_currency_rate_update')._trigger()
        return result

    @api.model
    def _cron_update_rates(self):
        """Daily pull of today's FX rates for every active Currency, once
        per company (multi-company: each company's own currency is its own
        base). Best-effort by design - a network hiccup or malformed
        response logs a warning and leaves whatever rates are already on
        file untouched, rather than failing the whole cron run (and
        blocking every other scheduled action queued behind it).
        """
        for company in self.env['res.company'].sudo().search([]):
            self._update_rates_for_company(company)

    def _update_rates_for_company(self, company):
        base = company.currency_id
        try:
            response = requests.get(RATE_API_URL.format(base=base.name), timeout=RATE_API_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception:
            _logger.warning(
                "Currency rate update failed for company %s (base %s)", company.name, base.name, exc_info=True)
            return

        rates = data.get('rates') or {}
        if data.get('result') != 'success' or not rates:
            _logger.warning(
                "Currency rate update: unexpected response for base %s: %s", base.name, data)
            return

        # active_test=True forced explicitly - relying on the ambient
        # context here is not safe: write() below calls this from whatever
        # recordset triggered the active toggle, which can itself carry
        # active_test=False (e.g. the Currencies list's own "Archived"
        # filter) and would otherwise pull in every inactive currency too.
        currencies = self.sudo().with_context(active_test=True).search(
            [('name', 'in', list(rates.keys())), ('id', '!=', base.id)])
        today = fields.Date.context_today(self)
        rate_model = self.env['res.currency.rate'].sudo()
        for currency in currencies:
            rate = rates.get(currency.name)
            if not rate:
                continue
            existing = rate_model.search([
                ('currency_id', '=', currency.id),
                ('name', '=', today),
                ('company_id', '=', company.id),
            ], limit=1)
            if existing:
                existing.rate = rate
            else:
                rate_model.create({
                    'currency_id': currency.id,
                    'name': today,
                    'rate': rate,
                    'company_id': company.id,
                })
        _logger.info(
            "Currency rate update: refreshed %s rate(s) for company %s (base %s)",
            len(currencies), company.name, base.name)
