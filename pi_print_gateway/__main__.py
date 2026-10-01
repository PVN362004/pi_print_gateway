import os

import uvicorn

from .config import load_config


if __name__ == '__main__':
    config = load_config(os.environ.get('PI_PRINT_CONFIG', 'config.yml'))
    server = config['server']
    uvicorn.run(
        'pi_print_gateway.main:app',
        host=str(server['host']),
        port=int(server['port']),
        workers=1,
    )
