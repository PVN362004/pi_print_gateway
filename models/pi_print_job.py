import logging
from base64 import b64decode, b64encode
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


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
    copies = fields.Integer(string='Số bản in', default=1, readonly=True)
    reprint_of_id = fields.Many2one('pi.print.job', string='In lại từ lệnh', readonly=True, ondelete='set null')
    reprint_ids = fields.One2many('pi.print.job', 'reprint_of_id', string='Các lần in lại', readonly=True)
    pdf_data = fields.Binary(string='Bản PDF đã gửi', attachment=True, readonly=True)
    pdf_filename = fields.Char(string='Tên file PDF', readonly=True)
    zpl_data = fields.Binary(string='Lệnh ZPL đã gửi', attachment=True, readonly=True)
    zpl_filename = fields.Char(string='Tên file ZPL', readonly=True)
    status = fields.Selection(
        [
            ('pending', 'Đang chuẩn bị'),
            ('waiting_network', 'Chờ kết nối'),
            ('sent', 'Đã gửi đến Gateway'),
            ('error', 'Có lỗi'),
        ],
        required=True,
        default='pending',
        readonly=True,
    )
    response_message = fields.Text(string='Phản hồi từ Gateway', readonly=True)
    retry_count = fields.Integer(string='Số lần thử lại', default=0, readonly=True)
    next_retry_at = fields.Datetime(string='Thử lại lúc', readonly=True)
    last_attempt_at = fields.Datetime(string='Lần gửi gần nhất', readonly=True)

    def _schedule_network_retry(self, error):
        """Keep the rendered payload and retry after a bounded backoff."""
        self.ensure_one()
        retry_count = self.retry_count + 1
        delay_minutes = min(2 ** min(retry_count - 1, 4), 15)
        self.write({
            'status': 'waiting_network',
            'retry_count': retry_count,
            'next_retry_at': fields.Datetime.now() + timedelta(minutes=delay_minutes),
            'last_attempt_at': fields.Datetime.now(),
            'response_message': _(
                'Không kết nối được Gateway: %(error)s. Hệ thống sẽ tự thử lại sau %(minutes)s phút.'
            ) % {'error': str(error), 'minutes': delay_minutes},
        })

    def _retry_job(self):
        self.ensure_one()
        if not self.gateway_id.active:
            self.write({
                'status': 'error',
                'next_retry_at': False,
                'response_message': _('Gateway đã bị vô hiệu hóa; không thể tự gửi lại.'),
            })
            return {'handled': False, 'message': self.response_message}
        files = self._stored_files()
        if not files:
            self.write({
                'status': 'error',
                'next_retry_at': False,
                'response_message': _('Không còn file PDF/ZPL đã lưu để gửi lại.'),
            })
            return {'handled': False, 'message': self.response_message}
        self.write({
            'status': 'pending',
            'next_retry_at': False,
            'last_attempt_at': fields.Datetime.now(),
        })
        return self.gateway_id.sudo()._send_job_to_gateway(self, files, max(self.copies, 1))

    @api.model
    def _cron_retry_waiting_jobs(self, limit=10):
        jobs = self.sudo().search([
            ('status', '=', 'waiting_network'),
            ('next_retry_at', '<=', fields.Datetime.now()),
        ], order='next_retry_at, id', limit=limit)
        for job in jobs:
            try:
                with self.env.cr.savepoint():
                    job._retry_job()
            except Exception as error:  # Do not let one corrupt job block the remaining queue.
                _logger.exception('Unexpected error while retrying Pi print job %s', job.id)
                job.write({
                    'status': 'error',
                    'next_retry_at': False,
                    'response_message': _('Không thể gửi lại lệnh in: %s') % str(error),
                })

    def action_retry_now(self):
        self.ensure_one()
        result = self.sudo()._retry_job()
        queued = self.status == 'waiting_network'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gửi lại lệnh in'),
                'message': result.get('message') or self.response_message,
                'type': 'warning' if queued else ('success' if result.get('handled') else 'danger'),
                'sticky': queued or not result.get('handled'),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _stored_files(self):
        self.ensure_one()
        files = {}
        if self.pdf_data:
            files['pdf_file'] = (
                self.pdf_filename or 'odoo-report.pdf',
                b64decode(self.pdf_data),
                'application/pdf',
            )
        if self.zpl_data:
            files['zpl_file'] = (
                self.zpl_filename or 'odoo-label.zpl',
                b64decode(self.zpl_data),
                'application/vnd.zebra-zpl',
            )
        return files

    def _files_for_reprint(self):
        """Use the saved payload; render again only for jobs created before this feature."""
        self.ensure_one()
        files = self._stored_files()
        if files:
            return files

        docids = [int(record_id) for record_id in (self.document_ids or '').split(',') if record_id.isdigit()]
        if not self.report_name or not docids:
            raise UserError(_(
                'Lệnh in cũ không có file đã lưu và không đủ thông tin chứng từ để tạo lại file.'
            ))
        report = self.env['ir.actions.report']._get_report_from_name(self.report_name)
        report_service = self.env['ir.actions.report'].with_company(self.company_id)
        if report.report_type == 'qweb-text':
            content = report_service._render_qweb_text(self.report_name, docids)[0]
            return {
                'zpl_file': (
                    '%s.zpl' % self.name.replace('/', '_'),
                    content,
                    'application/vnd.zebra-zpl',
                ),
            }
        if self.selected_format == 'zpl':
            raise UserError(_(
                'Lệnh in ZPL cũ này không có file đã lưu nên không thể tạo lại chính xác. '
                'Hãy in lại từ chứng từ gốc; các lệnh in mới sẽ lưu file ZPL để in lại.'
            ))
        content = report_service._render_qweb_pdf(self.report_name, docids)[0]
        return {
            'pdf_file': (
                '%s.pdf' % self.name.replace('/', '_'),
                content,
                'application/pdf',
            ),
        }

    def action_reprint(self):
        """Create a new job and submit the original rendered PDF/ZPL again."""
        self.ensure_one()
        if not self.gateway_id.active:
            raise UserError(_('Gateway của lệnh in này hiện không hoạt động.'))

        files = self._files_for_reprint()

        new_job = self.sudo().create({
            'name': _('%s (in lại)') % self.name,
            'gateway_id': self.gateway_id.id,
            'company_id': self.company_id.id,
            'user_id': self.env.user.id,
            'report_name': self.report_name,
            'document_model': self.document_model,
            'document_ids': self.document_ids,
            'printer_name': self.printer_name,
            'copies': max(self.copies, 1),
            'pdf_data': b64encode(files['pdf_file'][1]) if files.get('pdf_file') else False,
            'pdf_filename': files['pdf_file'][0] if files.get('pdf_file') else False,
            'zpl_data': b64encode(files['zpl_file'][1]) if files.get('zpl_file') else False,
            'zpl_filename': files['zpl_file'][0] if files.get('zpl_file') else False,
            'reprint_of_id': self.id,
            'status': 'pending',
        })
        result = self.gateway_id.sudo()._send_job_to_gateway(new_job, files, new_job.copies)
        notification_type = 'warning' if result.get('queued') else ('success' if result['handled'] else 'danger')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('In lại'),
                'message': result['message'],
                'type': notification_type,
                'sticky': bool(result.get('queued')) or not result['handled'],
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
