"""Tenant-scoped write locks for inventory and money.

Lock order is always assets -> contracts/sales -> their child rows.  In
particular, do not use joinedload(outer joins) with FOR UPDATE on PostgreSQL.
No helper commits: the caller owns the entire business transaction.
"""
from flask import abort
from flask_login import current_user
from sqlalchemy.orm import selectinload
from .extensions import db
from .models import Asset, Contract, Sale


def lock_asset(asset_id, *, required=True):
    item = (Asset.query.filter_by(id=asset_id, organization_id=current_user.organization_id)
            .options(selectinload(Asset.contracts), selectinload(Asset.sales), selectinload(Asset.investments))
            .populate_existing().with_for_update(of=Asset).first())
    if item is None and required:
        abort(404)
    return item


def lock_contract(contract_id):
    # Only read the FK first. The model + children are refreshed AFTER locking
    # the shared asset, so a waiter sees the preceding transaction's commit.
    ref = db.session.query(Contract.asset_id).filter_by(
        id=contract_id, organization_id=current_user.organization_id).first()
    if ref is None:
        abort(404)
    lock_asset(ref.asset_id)
    item = (Contract.query.filter_by(id=contract_id, organization_id=current_user.organization_id)
            .options(selectinload(Contract.installments), selectinload(Contract.payments),
                     selectinload(Contract.payment_promises))
            .populate_existing().with_for_update(of=Contract).first())
    if item is None:
        abort(404)
    return item


def lock_sale(sale_id):
    ref = db.session.query(Sale.asset_id).filter_by(
        id=sale_id, organization_id=current_user.organization_id).first()
    if ref is None:
        abort(404)
    lock_asset(ref.asset_id)
    sale = (Sale.query.filter_by(id=sale_id, organization_id=current_user.organization_id)
            .populate_existing().with_for_update(of=Sale).first())
    if sale is None:
        abort(404)
    return sale
