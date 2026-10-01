import json
import logging
import re
from base64 import b64encode
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


class PiPrintGateway(models.Model):
    _name = 'pi.print.gateway'
    _description = 'Cổng in Raspberry Pi'
    _order = 'sequence, name'

    name = fields.Char(string='Tên cổng in', required=True)
    sequence = fields.Integer(string='Thứ tự ưu tiên', default=10)
    active = fields.Boolean(string='Đang hoạt động', default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    base_url = fields.Char(
        string='Địa chỉ Gateway',
        required=True,
        default='http://raspberrypi.local:8080',
        help='Địa chỉ dịch vụ in trên Raspberry Pi/Linux, ví dụ http://10.119.54.97:8080.',
    )
    api_key = fields.Char(
        string='Khóa API',
        required=True,
        groups='base.group_system',
    )
    default_printer = fields.Char(
        string='Hồ sơ máy in',
        help='Tên hồ sơ máy in trong config.yml, ví dụ brother_pdf. Để trống để Pi tự chọn theo quy tắc hoặc máy in mặc định.',
    )
    timeout = fields.Integer(string='Thời gian chờ (giây)', default=30, required=True)
    verify_ssl = fields.Boolean(string='Xác minh chứng chỉ SSL', default=True)
    last_check = fields.Datetime(string='Lần kiểm tra gần nhất', readonly=True)
    last_check_message = fields.Char(string='Kết quả kiểm tra', readonly=True)

    @api.constrains('base_url')
    def _check_base_url(self):
        for gateway in self:
            parsed = urlparse(gateway.base_url or '')
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                raise ValidationError(_('Địa chỉ Gateway phải là URL HTTP hoặc HTTPS hợp lệ.'))

    @api.constrains('timeout')
    def _check_timeout(self):
        for gateway in self:
            if not 1 <= gateway.timeout <= 300:
                raise ValidationError(_('Thời gian chờ phải từ 1 đến 300 giây.'))

    def _headers(self):
        self.ensure_one()
        return {
            'Authorization': 'Bearer %s' % self.api_key,
            'Accept': 'application/json',
        }

    def _url(self, path):
        self.ensure_one()
        return '%s/%s' % (self.base_url.rstrip('/'), path.lstrip('/'))

    def action_test_connection(self):
        self.ensure_one()
        try:
            response = requests.get(
                self._url('/api/v1/health'),
                headers=self._headers(),
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            payload = response.json()
            unavailable = [
                printer.get('name')
                for printer in payload.get('printers', [])
                if not printer.get('available', True)
            ]
            if unavailable:
                message = _('Đã kết nối, nhưng các hàng đợi CUPS sau chưa sẵn sàng: %s') % ', '.join(unavailable)
                notification_type = 'warning'
            else:
                message = _('Đã kết nối: %s') % payload.get('status', 'ok')
                notification_type = 'success'
            self.write({
                'last_check': fields.Datetime.now(),
                'last_check_message': message,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cổng in Raspberry Pi'),
                    'message': message,
                    'type': notification_type,
                    'sticky': bool(unavailable),
                },
            }
        except (requests.RequestException, ValueError) as error:
            message = _('Kết nối thất bại: %s') % str(error)
            self.write({
                'last_check': fields.Datetime.now(),
                'last_check_message': message,
            })
            raise UserError(message) from error

    @api.model
    def _safe_filename(self, value, extension):
        clean = re.sub(r'[^A-Za-z0-9_.-]+', '_', value or 'odoo-report').strip('._')
        return '%s.%s' % (clean or 'odoo-report', extension)

    @api.model
    def _get_document_ids(self, action):
        action_context = action.get('context') or {}
        ids = action_context.get('active_ids') or []
        return [int(record_id) for record_id in ids if str(record_id).isdigit()]

    @api.model
    def _render_files(self, action):
        report_name = action.get('report_name')
        if not report_name:
            raise UserError(_('The report action does not contain a report name.'))

        report = self.env['ir.actions.report']._get_report_from_name(report_name)
        docids = self._get_document_ids(action)
        data = action.get('data') or None
        render_docids = None if data else docids
        action_context = dict(action.get('context') or {})
        report_service = self.env['ir.actions.report'].with_context(**action_context)
        display_name = action.get('display_name') or action.get('name') or report.name
        files = {}

        if action.get('report_type') == 'qweb-text':
            text_content = report_service._render_qweb_text(
                report_name, render_docids, data=data
            )[0]
            files['zpl_file'] = (
                action.get('pi_print_zpl_filename') or self._safe_filename(display_name, 'txt'),
                text_content,
                'text/plain',
            )
        else:
            pdf_content = report_service._render_qweb_pdf(
                report_name, render_docids, data=data
            )[0]
            files['pdf_file'] = (
                action.get('pi_print_pdf_filename') or self._safe_filename(display_name, 'pdf'),
                pdf_content,
                'application/pdf',
            )

        custom_zpl = action.get('pi_print_zpl')
        if custom_zpl:
            files['zpl_file'] = (
                action.get('pi_print_zpl_filename') or self._safe_filename(display_name, 'zpl'),
                custom_zpl.encode('utf-8') if isinstance(custom_zpl, str) else custom_zpl,
                'application/vnd.zebra-zpl',
            )

        return report, docids, files

    def _send_job_to_gateway(self, job, files, copies):
        """Send already-rendered files to Pi and update the supplied job."""
        self.ensure_one()
        form_data = {
            'source': 'odoo',
            'source_job_id': str(job.id),
            'title': job.name,
            'printer': job.printer_name or '',
            'copies': str(copies),
            'format': 'auto',
            'metadata': json.dumps({
                'database': self.env.cr.dbname,
                'company_id': job.company_id.id,
                'user_id': job.user_id.id,
                'report_name': job.report_name,
                'model': job.document_model,
                'res_ids': [int(record_id) for record_id in (job.document_ids or '').split(',') if record_id.isdigit()],
            }),
        }
        try:
            response = requests.post(
                self._url('/api/v1/jobs'),
                headers=self._headers(),
                data=form_data,
                files=files,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            payload = response.json()
            selected_format = payload.get('selected_format')
            if selected_format not in ('pdf', 'zpl', 'text'):
                selected_format = False
            job.write({
                'status': 'sent',
                'remote_job_id': str(payload.get('job_id') or ''),
                'selected_format': selected_format,
                'response_message': payload.get('message') or payload.get('status') or 'accepted',
            })
            return {
                'handled': True,
                'job_id': job.id,
                'remote_job_id': payload.get('job_id'),
                'printer': payload.get('printer') or job.printer_name,
                'selected_format': selected_format,
                'message': payload.get('message') or _('Đã gửi lệnh in đến Gateway.'),
            }
        except (requests.RequestException, ValueError) as error:
            _logger.exception('Unable to send Odoo report %s to Pi gateway', job.report_name)
            job.write({
                'status': 'error',
                'response_message': str(error),
            })
            return {
                'handled': False,
                'gateway_error': True,
                'job_id': job.id,
                'message': _('Lỗi Gateway: %s') % str(error),
            }

    @api.model
    def _submit_report_action(self, action):
        company = self.env.company
        if not company.pi_print_enabled:
            return {'handled': False, 'reason': 'disabled'}

        gateway = company.pi_print_gateway_id.sudo()
        if not gateway or not gateway.active:
            return {
                'handled': False,
                'gateway_error': True,
                'reason': 'no_gateway',
                'message': _('Pi Print Gateway is enabled but no active gateway is configured.'),
            }

        report, docids, files = self._render_files(action)
        action_context = action.get('context') or {}
        printer_name = (
            action.get('pi_printer_name')
            or action_context.get('pi_printer_name')
            or gateway.default_printer
            or ''
        )
        try:
            copies = max(1, min(int(action.get('pi_print_copies') or 1), 100))
        except (TypeError, ValueError):
            copies = 1

        display_name = action.get('display_name') or action.get('name') or report.name
        job = self.env['pi.print.job'].sudo().create({
            'name': display_name,
            'gateway_id': gateway.id,
            'company_id': company.id,
            'user_id': self.env.user.id,
            'report_name': action.get('report_name'),
            'document_model': report.model,
            'document_ids': ','.join(str(record_id) for record_id in docids),
            'printer_name': printer_name,
            'copies': copies,
            'pdf_data': b64encode(files['pdf_file'][1]) if files.get('pdf_file') else False,
            'pdf_filename': files['pdf_file'][0] if files.get('pdf_file') else False,
            'zpl_data': b64encode(files['zpl_file'][1]) if files.get('zpl_file') else False,
            'zpl_filename': files['zpl_file'][0] if files.get('zpl_file') else False,
            'status': 'pending',
        })
        result = gateway._send_job_to_gateway(job, files, copies)
        result['download_original'] = company.pi_print_behavior == 'gateway_and_download'
        if not result['handled']:
            result['message'] = _('%s Báo cáo sẽ được tải về thay vì in.') % result['message']
        return result
