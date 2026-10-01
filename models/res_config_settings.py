from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pi_print_enabled = fields.Boolean(
        related='company_id.pi_print_enabled',
        readonly=False,
    )
    pi_print_gateway_id = fields.Many2one(
        related='company_id.pi_print_gateway_id',
        readonly=False,
    )
    pi_print_behavior = fields.Selection(
        related='company_id.pi_print_behavior',
        readonly=False,
    )
