from odoo import fields, models


class PiPrintJob(models.Model):
    _name = 'pi.print.job'
    _description = 'Lệnh in qua Raspberry Pi'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Tên lệnh in', required=True, readonly=True)
    gateway_id = fields.Many2one('pi.print.gateway', string='Gateway', required=True, readonly=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', string='Công ty', required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Người gửi lệnh', required=True, readonly=True)
    report_name = fields.Char(string='Tên báo cáo kỹ thuật', readonly=True)
    document_model = fields.Char(string='Model chứng từ', readonly=True)
    document_ids = fields.Char(string='ID chứng từ', readonly=True)
    printer_name = fields.Char(string='Hồ sơ máy in', readonly=True)
    selected_format = fields.Selection([('pdf', 'PDF'), ('zpl', 'ZPL'), ('text', 'Văn bản')], string='Định dạng đã gửi', readonly=True)
    remote_job_id = fields.Char(string='Mã lệnh trên Pi', readonly=True)
    status = fields.Selection(
        [
            ('pending', 'Đang chuẩn bị'),
            ('sent', 'Đã gửi đến Gateway'),
            ('error', 'Có lỗi'),
        ],
        required=True,
        default='pending',
        readonly=True,
    )
    response_message = fields.Text(string='Phản hồi từ Gateway', readonly=True)
