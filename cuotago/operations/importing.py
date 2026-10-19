"""Two-phase, tenant-scoped CSV imports. Preview never mutates the business ledger."""
import csv
import hashlib
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from ..models import Asset, Client, Contract, Installment, Organization
from ..business_time import utcnow, business_date
from ..money_ops import money, integer
from ..schedules import due_dates, FREQUENCIES
from .models import ImportBatch, BankLine, MoneyEntry
from .common import audit, scoped

COLUMNS = {
    'clients': ['external_id', 'full_name', 'document_id', 'phone', 'email', 'address'],
    'balances': ['external_id', 'client_id', 'description', 'total', 'paid', 'balance', 'first_due', 'count', 'frequency', 'cost'],
    'bank': ['external_id', 'date', 'amount', 'reference'],
}


def short(value, maximum, required=False):
    value = str(value or '').strip()
    if len(value) > maximum or (required and not value):
        raise ValueError('Campo requerido vacio o texto demasiado largo.')
    return value


def parse_csv(payload, kind):
    if kind not in COLUMNS:
        raise ValueError('Tipo de importacion no valido.')
    if not payload or len(payload) > 1024 * 1024:
        raise ValueError('Usa un CSV UTF-8 de hasta 1 MB y 500 filas.')
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('El archivo debe estar guardado como CSV UTF-8.') from None
    first = text.splitlines()[0] if text.splitlines() else ''
    delimiter = ';' if first.count(';') > first.count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('Encabezados ausentes o repetidos.')
    if set(reader.fieldnames) != set(COLUMNS[kind]):
        raise ValueError('Encabezados esperados: ' + ', '.join(COLUMNS[kind]))
    rows = []
    seen = set()
    documents = set()
    for number, raw in enumerate(reader, 2):
        try:
            if None in raw or any(v is None for v in raw.values()):
                raise ValueError('La fila tiene una cantidad incorrecta de columnas.')
            row = {k: v.strip() for k, v in raw.items()}
            key = short(row['external_id'], 120, True)
            if key in seen:
                raise ValueError('El identificador externo esta repetido.')
            seen.add(key)
            if kind == 'clients':
                short(row['full_name'], 140, True)
                if row['document_id']:
                    if row['document_id'] in documents:
                        raise ValueError('Documento repetido dentro del archivo.')
                    documents.add(row['document_id'])
                for field, maximum in [('document_id', 80), ('phone', 40), ('email', 160), ('address', 240)]:
                    short(row[field], maximum)
                if row['email'] and ('@' not in row['email'] or '.' not in row['email']):
                    raise ValueError('Correo no valido.')
            elif kind == 'balances':
                row['client_id'] = integer(row['client_id'])
                for field in ['total', 'paid', 'balance', 'cost']:
                    row[field] = str(money(row[field] or 0))
                total, paid, balance, cost = [money(row[k]) for k in ['total', 'paid', 'balance', 'cost']]
                if total <= 0 or min(paid, balance, cost) < 0 or cost > total or total != paid + balance:
                    raise ValueError('Total debe ser igual a pagado + saldo, sin montos negativos; costo no supera total.')
                row['count'] = integer(row['count'], 1, 120)
                if balance and row['count'] > int(balance * 100):
                    raise ValueError('Hay mas cuotas que centavos de saldo.')
                first_due = date.fromisoformat(row['first_due'])
                list(due_dates(first_due, row['frequency'], row['count']))
                short(row['description'], 140, True)
            else:
                date.fromisoformat(row['date'])
                row['amount'] = str(money(row['amount']))
                if money(row['amount']) == 0:
                    raise ValueError('No se importan movimientos bancarios de importe cero.')
                short(row['reference'], 120)
            rows.append(row)
            if len(rows) > 500:
                raise ValueError('El limite es 500 filas por archivo.')
        except (ValueError, KeyError) as error:
            raise ValueError(f'Fila {number}: {error}') from None
    if not rows:
        raise ValueError('El archivo no contiene registros.')
    return rows


def import_key(org, kind, external_id):
    return hashlib.sha256(f'{org}:{kind}:{external_id}'.encode()).hexdigest()


def validate_existing(s, org, kind, rows, account=''):
    for number, row in enumerate(rows, 2):
        key = import_key(org, kind, row['external_id'])
        if kind == 'clients':
            existing = s.query(Client).filter_by(organization_id=org, import_key=key).first()
            if existing or (row['document_id'] and s.query(Client).filter_by(organization_id=org, document_id=row['document_id']).first()):
                raise ValueError(f'Fila {number}: cliente existente o documento repetido; no se sobrescribe.')
        elif kind == 'balances':
            scoped(s, Client, org, row['client_id'])
            if s.query(Contract).filter_by(organization_id=org, request_key=key).first():
                raise ValueError(f'Fila {number}: este saldo ya fue importado.')
        else:
            if s.query(BankLine).filter_by(organization_id=org, account=account, external_id=row['external_id']).first():
                raise ValueError(f'Fila {number}: movimiento bancario ya importado.')


def preview_import(s, org, actor, kind, payload, account=''):
    rows = parse_csv(payload, kind)
    account = short(account, 80, kind == 'bank')
    validate_existing(s, org, kind, rows, account)
    normalized = json.dumps({'rows': rows, 'account': account}, sort_keys=True, ensure_ascii=False)
    batch = ImportBatch(organization_id=org, actor_id=actor, kind=kind,
        digest=hashlib.sha256(normalized.encode()).hexdigest(), payload=normalized,
        expires_at=utcnow() + timedelta(hours=1))
    s.add(batch)
    s.flush()
    return batch, rows


def apply_import(s, org, actor, batch_id, fingerprint, zone):
    # Serializes concurrent import confirmations within a tenant; no partial commits.
    s.query(Organization).filter_by(id=org).with_for_update(of=Organization).one()
    batch = scoped(s, ImportBatch, org, batch_id, lock=True)
    if batch.actor_id != actor:
        raise PermissionError('Confirma con el mismo usuario que preparo la importacion.')
    if fingerprint != batch.digest:
        raise ValueError('La vista previa no coincide con el archivo.')
    if batch.applied_at:
        return batch
    if batch.expires_at <= utcnow():
        raise ValueError('La vista previa vencio. Vuelve a cargar el archivo.')
    if hashlib.sha256(batch.payload.encode()).hexdigest() != batch.digest:
        raise ValueError('Fallo la integridad de la vista previa.')
    payload = json.loads(batch.payload)
    rows, account = payload['rows'], payload['account']
    validate_existing(s, org, batch.kind, rows, account)
    for row in rows:
        key = import_key(org, batch.kind, row['external_id'])
        if batch.kind == 'clients':
            s.add(Client(organization_id=org, import_key=key, full_name=row['full_name'],
                document_id=row['document_id'] or None, phone=row['phone'] or None,
                email=row['email'] or None, address=row['address'] or None))
        elif batch.kind == 'balances':
            total, paid, balance, cost = [money(row[k]) for k in ['total', 'paid', 'balance', 'cost']]
            asset = Asset(organization_id=org, name=row['description'], kind='other',
                is_virtual=True, quantity_total=0, estimated_value=0, sale_price=0, status='sold')
            contract = Contract(organization_id=org, client_id=row['client_id'], asset=asset,
                request_key=key, code=f'IMP-{org}-{key[:20]}', deal_type='credit_sale',
                total_amount=total, base_amount=cost, opening_paid=paid, down_payment=0,
                imported_on=business_date(utcnow(), zone), inventory_released=True,
                installment_amount=money(balance / row['count']), quantity=1,
                start_date=business_date(utcnow(), zone), first_due_date=date.fromisoformat(row['first_due']),
                frequency=row['frequency'], daily_late_interest=0,
                status='active' if balance else 'completed',
                notes=f'Saldo inicial importado ({row["external_id"]}). Pagado historico: {paid}. No es ingreso nuevo ni reposicion de inventario.')
            if balance:
                base, extra = divmod(int(balance * 100), row['count'])
                for i, due in enumerate(due_dates(contract.first_due_date, contract.frequency, row['count'])):
                    contract.installments.append(Installment(sequence=i + 1, due_date=due,
                        amount=Decimal(base + (1 if i < extra else 0)) / 100, paid_amount=0,
                        late_fee_amount=0, late_fee_base_amount=0, late_fee_paid=0))
            s.add_all([asset, contract])
        else:
            s.add(BankLine(organization_id=org, account=account, external_id=row['external_id'],
                date=date.fromisoformat(row['date']), amount=money(row['amount']),
                reference=row['reference'], batch_id=batch.id))
        s.flush()
    batch.applied_at, batch.applied_count = utcnow(), len(rows)
    audit(s, org, actor, 'data.imported', 'import_batch', batch.id,
          f'Importacion confirmada: {len(rows)} registros.', {'kind': batch.kind, 'digest': batch.digest})
    return batch


def match_bank_line(s, org, actor, bank_id, entry_id, reason, zone):
    line = scoped(s, BankLine, org, bank_id, lock=True)
    entry = scoped(s, MoneyEntry, org, entry_id, lock=True)
    if line.money_entry_id or s.query(BankLine).filter_by(money_entry_id=entry.id).first():
        raise ValueError('Uno de los movimientos ya esta conciliado.')
    if entry.method == 'cash' or money(entry.amount) != money(line.amount):
        raise ValueError('Debe ser un movimiento no efectivo con el mismo importe y signo.')
    if abs((line.date - business_date(entry.occurred_at, zone)).days) > 7:
        raise ValueError('Las fechas difieren mas de siete dias; revisa antes de conciliar.')
    if len((reason or '').strip()) < 5:
        raise ValueError('Anota la evidencia de la coincidencia.')
    line.money_entry_id, line.matched_by, line.matched_at = entry.id, actor, utcnow()
    audit(s, org, actor, 'bank.matched', 'bank_line', line.id,
          'Conciliacion manual confirmada.', {'entry': entry.id, 'evidence': reason[:240]})
    return line
