{
    'name': 'Pi Print Gateway',
    'version': '19.0.1.0.1',
    'category': 'Productivity',
    'summary': 'Gửi báo cáo Odoo PDF/ZPL qua Raspberry Pi và CUPS',
    'author': 'Nhan',
    'license': 'AGPL-3',
    'depends': ['base_setup', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/pi_print_gateway_views.xml',
        'views/pi_print_job_views.xml',
        'views/res_config_settings_views.xml',
        'views/pi_print_gateway_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pi_print_gateway/static/src/js/report_handler.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
