"""Service helpers. Callers own transactions; never commit inside services."""
import hashlib
import json
import re
from sqlalchemy import text
from ..models import TenantAuditLog
from .models import OperationRequest


def audit(s, org, actor, action, entity, identifier, summary, detail=None):
    s.add(TenantAuditLog(organization_id=org, actor_user_id=actor, action=action,
          entity_type=entity, entity_id=str(identifier), summary=summary[:240],
          detail=json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None))


def scoped(s, model, org, identifier, lock=False):
    q = s.query(model).filter_by(id=identifier, organization_id=org)
    if lock:
        q = q.populate_existing().with_for_update(of=model)
    result = q.first()
    if result is None:
        raise LookupError('Registro no encontrado.')
    return result


def operation(s, org, scope, key, payload):
    """Same key + same payload replays; changed payload fails. Serialize only that key.

    PostgreSQL advisory transaction lock prevents insert races and is released on
    rollback too. The UNIQUE constraint remains the final integrity boundary.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', key or ''):
        raise ValueError('Formulario vencido. Recarga la pagina para obtener una clave de operacion.')
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    fingerprint = hashlib.sha256(raw).hexdigest()
    lock_digest = hashlib.sha256(f'{org}:{scope}:{key}'.encode()).digest()[:8]
    if s.get_bind().dialect.name == 'postgresql':
        s.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int.from_bytes(lock_digest, 'big', signed=True)})
    row = s.query(OperationRequest).filter_by(organization_id=org, scope=scope, request_key=key).first()
    if row:
        if row.payload_hash != fingerprint:
            raise ValueError('La misma clave ya se uso con datos diferentes. Abre un formulario nuevo.')
        if row.result_id is None:
            raise ValueError('La operacion no tiene confirmacion. Consulta auditoria antes de repetirla.')
        return row, True
    row = OperationRequest(organization_id=org, scope=scope, request_key=key, payload_hash=fingerprint)
    s.add(row)
    s.flush()
    return row, False
