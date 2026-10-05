"""Portable tenant export helpers. This is NOT a database backup/restore format."""
import csv
import hashlib
import io
import json
from pathlib import PurePosixPath
from .dealer_summary import csv_cell


class ExportWriter:
    def __init__(self, archive):
        self.archive = archive
        self.entries = []

    def _path(self, name):
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('Unsafe archive path')
        return path.as_posix()

    def write_bytes(self, name, data, *, rows=None):
        name = self._path(name)
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.archive.writestr(name, data)
        entry = {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if rows is not None:
            entry['rows'] = rows
        self.entries.append(entry)

    def write_csv(self, name, headers, rows):
        # Stream rows directly into the compressed member, retaining only one row.
        name = self._path(name)
        digest = hashlib.sha256()
        size = 0
        count = 0
        with self.archive.open(name, 'w', force_zip64=True) as out:
            row_buffer = io.StringIO(newline='')
            writer = csv.writer(row_buffer)
            bom = b'\xef\xbb\xbf'
            out.write(bom); digest.update(bom); size += len(bom)
            for row in _with_header(headers, rows):
                writer.writerow([csv_cell(value) for value in row])
                payload = row_buffer.getvalue().encode('utf-8')
                out.write(payload); digest.update(payload); size += len(payload)
                row_buffer.seek(0); row_buffer.truncate(0)
                count += 1
        self.entries.append({'path': name, 'bytes': size, 'sha256': digest.hexdigest(), 'rows': count - 1})

    def manifest(self, organization_id, generated_at):
        self.archive.writestr('manifest.json', json.dumps({
            'format': 'cuotago-data-export/v1',
            'organization_id': organization_id,
            'generated_at': generated_at,
            'database_backup': False,
            'automatic_restore': False,
            'contains_internal_costs': True,
            'files': self.entries,
        }, ensure_ascii=False, indent=2).encode('utf-8'))


def _with_header(headers, rows):
    yield headers
    yield from rows


def image_export_path(asset):
    ext = {'image/webp': 'webp', 'image/jpeg': 'jpg', 'image/png': 'png'}.get(asset.image_mime)
    return f'imagenes/inventario-{int(asset.id)}.{ext}' if ext else ''
