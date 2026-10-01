from odoo import http
from odoo.http import request


class PiPrintGatewayController(http.Controller):

    @http.route('/pi_print_gateway/submit_report', type='jsonrpc', auth='user')
    def submit_report(self, action):
        return request.env['pi.print.gateway']._submit_report_action(action)
