from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    pi_print_enabled = fields.Boolean(string='Bật chuyển lệnh in qua Gateway')
    pi_print_gateway_id = fields.Many2one(
        'pi.print.gateway',
        string='Gateway mặc định',
        check_company=True,
    )
    pi_print_behavior = fields.Selection(
        [
            ('gateway_only', 'Chỉ gửi đến Gateway'),
            ('gateway_and_download', 'Gửi đến Gateway và tải file về'),
        ],
        string='Cách xử lý khi in',
        default='gateway_only',
        required=True,
    )
