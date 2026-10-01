/** @odoo-module **/

import { rpc } from '@web/core/network/rpc';
import { registry } from '@web/core/registry';
import { _t } from '@web/core/l10n/translation';

registry.category('ir.actions.report handlers').add(
    'pi_print_gateway.report_handler',
    async (action, options, env) => {
        if (!['qweb-pdf', 'qweb-text'].includes(action.report_type)) {
            return false;
        }
        if (action.context?.pi_print_bypass) {
            return false;
        }

        env.services.ui.block();
        try {
            const result = await rpc('/pi_print_gateway/submit_report', { action });
            if (!result.handled) {
                if (result.gateway_error) {
                    env.services.notification.add(result.message, {
                        title: _t('Print Gateway'),
                        type: 'warning',
                        sticky: true,
                    });
                }
                return false;
            }

            const details = [result.printer, result.selected_format?.toUpperCase()]
                .filter(Boolean)
                .join(' · ');
            env.services.notification.add(
                details ? `${result.message} (${details})` : result.message,
                {
                    title: _t('Print Gateway'),
                    type: result.queued ? 'warning' : 'success',
                    sticky: Boolean(result.queued),
                }
            );
            return !result.download_original;
        } catch (error) {
            console.error('Pi Print Gateway error', error);
            env.services.notification.add(
                _t('Cannot reach the print gateway. The report will be downloaded instead.'),
                {
                    title: _t('Print Gateway'),
                    type: 'warning',
                    sticky: true,
                }
            );
            return false;
        } finally {
            env.services.ui.unblock();
        }
    },
    { sequence: 10 }
);
