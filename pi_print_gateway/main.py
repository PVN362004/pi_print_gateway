import json
import os
import re
import secrets
import subprocess
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

from .adapters import create_adapter
from .config import load_config
from .models import Job


CONFIG_PATH = os.environ.get('PI_PRINT_CONFIG', 'config.yml')
CONFIG = load_config(CONFIG_PATH)
SERVER = CONFIG['server']
STORAGE = Path(SERVER['storage_dir']).expanduser()
STORAGE.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(SERVER['max_file_size_mb']) * 1024 * 1024

app = FastAPI(title='Pi Print Gateway', version='1.0.0')
JOBS: dict[str, Job] = {}
LOCK = threading.Lock()


def require_api_key(x_api_key: str | None, authorization: str | None) -> None:
    expected = str(SERVER.get('api_key', ''))
    bearer = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    supplied = bearer or x_api_key or ''
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail='Invalid API key')


def choose_printer(requested: str | None, metadata: dict[str, Any], extension: str = '') -> str:
    printers = CONFIG['printers']
    if requested:
        if requested not in printers:
            raise HTTPException(status_code=400, detail=f'Unknown printer profile: {requested}')
        return requested

    for rule in CONFIG.get('rules', []):
        match = rule.get('match') or {}
        expected_extension = str(match.get('extension', '')).lower().lstrip('.')
        if expected_extension and expected_extension != extension:
            continue
        expected_metadata = match.get('metadata', {})
        if any(metadata.get(key) != value for key, value in expected_metadata.items()):
            continue
        target = rule.get('printer')
        if target in printers:
            return target

    default_printer = CONFIG.get('default_printer')
    if default_printer in printers:
        return default_printer
    if printers:
        return next(iter(printers))
    raise HTTPException(status_code=503, detail='No printer profile is configured')


def printer_format(printer_config: dict[str, Any]) -> str:
    configured = str(printer_config.get('format', '')).lower()
    if configured:
        return configured
    allowed = {str(item).lower().lstrip('.') for item in printer_config.get('extensions', [])}
    if 'zpl' in allowed and 'pdf' not in allowed:
        return 'zpl'
    if len(allowed) == 1:
        return next(iter(allowed))
    return 'pdf'


def printer_status(name: str, printer_config: dict[str, Any]) -> dict[str, Any]:
    result = {
        'name': name,
        'format': printer_format(printer_config),
        'type': printer_config.get('type'),
        'printer_name': printer_config.get('printer_name'),
        'available': True,
    }
    if printer_config.get('type') == 'cups':
        try:
            check = subprocess.run(
                ['lpstat', '-p', str(printer_config['printer_name'])],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            result['message'] = check.stdout.strip()
        except (subprocess.SubprocessError, OSError, KeyError) as error:
            result.update({'available': False, 'message': str(error)})
    return result


async def store_upload(file: UploadFile, target_path: Path) -> int:
    total = 0
    with target_path.open('wb') as destination:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_BYTES:
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail='File is too large')
            destination.write(chunk)
    await file.close()
    return total


def submit_job(job_id: str) -> None:
    job = JOBS[job_id]
    try:
        job.update(status='printing')
        printer_config = CONFIG['printers'][job.printer]
        adapter = create_adapter(printer_config)
        result = adapter.submit(Path(job.stored_path), job.public_dict())
        job.update(status='submitted', adapter_response=result)
    except Exception as error:  # Keep the worker alive and expose failure through API.
        job.update(status='failed', error=str(error))
    finally:
        if SERVER.get('delete_after_submit') and job.status == 'submitted':
            Path(job.stored_path).unlink(missing_ok=True)


@app.get('/health')
@app.get('/api/v1/health')
def health(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key, authorization)
    return {
        'status': 'ok',
        'default_printer': CONFIG.get('default_printer'),
        'printers': [
            printer_status(name, values)
            for name, values in CONFIG['printers'].items()
        ],
    }


@app.get('/api/v1/printers')
def list_printers(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key, authorization)
    return {
        'default_printer': CONFIG.get('default_printer'),
        'printers': [printer_status(name, values) for name, values in CONFIG['printers'].items()],
    }


@app.post('/api/v1/jobs')
async def create_job(
    file: UploadFile | None = File(default=None),
    pdf_file: UploadFile | None = File(default=None),
    zpl_file: UploadFile | None = File(default=None),
    printer: str | None = Form(default=None),
    metadata: str = Form(default='{}'),
    source: str = Form(default='unknown'),
    source_job_id: str = Form(default=''),
    title: str = Form(default='Odoo report'),
    copies: int = Form(default=1, ge=1, le=100),
    format: str = Form(default='auto'),
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key, authorization)
    try:
        metadata_dict = json.loads(metadata)
        if not isinstance(metadata_dict, dict):
            raise ValueError
    except ValueError as error:
        raise HTTPException(status_code=400, detail='metadata must be a JSON object') from error

    generic_extension = Path(file.filename or '').suffix.lower().lstrip('.') if file else ''
    target_printer = choose_printer(printer, metadata_dict, generic_extension)
    target_config = CONFIG['printers'][target_printer]
    required_format = printer_format(target_config)
    if not re.fullmatch(r'[a-z0-9_-]+', format):
        raise HTTPException(status_code=400, detail='Invalid format')
    if format != 'auto' and format != required_format:
        raise HTTPException(
            status_code=409,
            detail=f'Printer {target_printer} requires {required_format}, not {format}',
        )

    if required_format == 'zpl':
        selected_upload = zpl_file
    elif required_format == 'pdf':
        selected_upload = pdf_file
    else:
        selected_upload = file
    if not selected_upload and file:
        extension = Path(file.filename or '').suffix.lower().lstrip('.')
        if extension == required_format or (required_format == 'zpl' and extension in ('txt', 'prn')):
            selected_upload = file
    if not selected_upload:
        raise HTTPException(
            status_code=422,
            detail=f'Printer {target_printer} requires a {required_format.upper()} file',
        )

    original_filename = Path(selected_upload.filename or f'print-job.{required_format}').name
    job_id = secrets.token_hex(12)
    target_path = STORAGE / f'{job_id}.{required_format}'
    await store_upload(selected_upload, target_path)

    metadata_dict.update({'source': source, 'source_job_id': source_job_id})
    job = Job(
        id=job_id,
        original_filename=original_filename,
        stored_path=str(target_path),
        extension=required_format,
        selected_format=required_format,
        printer=target_printer,
        title=title,
        copies=copies,
        metadata=metadata_dict,
    )
    with LOCK:
        JOBS[job_id] = job
    if target_config.get('type') == 'cups':
        submit_job(job_id)
        if job.status == 'failed':
            raise HTTPException(status_code=503, detail=job.error or 'CUPS rejected the job')
    else:
        threading.Thread(target=submit_job, args=(job_id,), daemon=True).start()
    response = job.public_dict()
    response.update({'job_id': job.id, 'message': f'Job queued for {target_printer}'})
    return response


@app.get('/api/v1/jobs/{job_id}')
def get_job(
    job_id: str,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key, authorization)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job.public_dict()


@app.post('/api/v1/jobs/{job_id}/cancel')
def cancel_job(
    job_id: str,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_api_key(x_api_key, authorization)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    job.update(status='cancelled')
    return job.public_dict()
