"""Real SQLAlchemy models/services on SQLite, without pretending to run Flask.
Imports the model definitions unchanged, replacing only framework extension
plumbing. These tests do NOT validate PostgreSQL locks, requests or auth cookies.
"""
import ast
import importlib.util
import sys
import types
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, relationship, backref
from decimal import Decimal
from datetime import datetime, date
ROOT=Path(__file__).resolve().parents[1]
PREFIX='_cuotago_v83_test'
_LOADED = None


def load():
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    for name in list(sys.modules):
        if name==PREFIX or name.startswith(PREFIX+'.'):
            del sys.modules[name]
    pkg=types.ModuleType(PREFIX);pkg.__path__=[str(ROOT/'cuotago')];sys.modules[PREFIX]=pkg
    ops=types.ModuleType(PREFIX+'.operations');ops.__path__=[str(ROOT/'cuotago/operations')];sys.modules[ops.__name__]=ops
    Base=declarative_base()
    db=types.SimpleNamespace(Model=Base,relationship=relationship,backref=backref)
    for n in ('Column','BigInteger','Integer','String','Text','Date','DateTime','Numeric','Boolean','ForeignKey','LargeBinary','UniqueConstraint','Index'):
        setattr(db,n,getattr(sa,n))
    ext=types.ModuleType(PREFIX+'.extensions');ext.db=db;sys.modules[ext.__name__]=ext
    model=types.ModuleType(PREFIX+'.models');model.__package__=PREFIX;model.__file__=str(ROOT/'cuotago/models.py')
    tree=ast.parse((ROOT/'cuotago/models.py').read_text())
    tree.body=[n for n in tree.body if not (isinstance(n,ast.ImportFrom) and n.module in ('flask_login','werkzeug.security','extensions'))]
    class Mixin:
        @property
        def is_authenticated(self):return True
    model.__dict__.update(db=db,UserMixin=Mixin,login_manager=types.SimpleNamespace(user_loader=lambda f:f),
        generate_password_hash=lambda p:'TEST-HASH:'+p,check_password_hash=lambda h,p:h=='TEST-HASH:'+p)
    sys.modules[model.__name__]=model;exec(compile(tree,model.__file__,'exec'),model.__dict__)
    new=__import__(PREFIX+'.operations.models',fromlist=['*'])
    _LOADED = (model,new,db)
    return _LOADED


def module(name):
    return __import__(PREFIX+'.'+name,fromlist=['*'])


def database():
    m,n,db=load();engine=sa.create_engine('sqlite:///:memory:')
    @sa.event.listens_for(engine,'connect')
    def fk(conn,rec):conn.execute('PRAGMA foreign_keys=ON')
    db.Model.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    s=Session(engine,expire_on_commit=False);db.session=s
    org=m.Organization(name='Empresa prueba',currency='DOP')
    other=m.Organization(name='Otra empresa',currency='DOP');s.add_all([org,other]);s.flush()
    u=m.User(organization_id=org.id,name='Dueno',email='owner@example.test',password_hash='test',role='owner')
    v=m.User(organization_id=other.id,name='Otro',email='other@example.test',password_hash='test',role='owner')
    c=m.Client(organization_id=org.id,full_name='Cliente')
    supplier=m.Supplier(organization_id=org.id,name='Proveedor')
    a=m.Asset(organization_id=org.id,name='Producto',kind='phone',quantity_total=10,estimated_value=Decimal('100'),sale_price=Decimal('200'),status='available')
    s.add_all([u,v,c,supplier,a]);s.commit()
    return types.SimpleNamespace(m=m,n=n,db=db,s=s,engine=engine,org=org,other=other,u=u,v=v,c=c,supplier=supplier,a=a)
