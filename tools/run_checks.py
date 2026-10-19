#!/usr/bin/env python3
"""Isolated tests in separate processes; explicit PostgreSQL acceptance gate.
Separate Python processes keep framework-independent AST fixtures from leaking
mock framework modules/mappers into real HTTP tests or one another.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import re
ROOT=Path(__file__).resolve().parents[1]
BASE_TESTS=[
 'test_agreement_motion_ui.py','test_customer_sale_receipt.py','test_dealer_workflows.py',
 'test_launcher_appearance_v82.py','test_launcher_ui_contract.py','test_layout_v79.py',
 'test_sw_performance.py','test_ui_restoration_v81.py','test_workspace_ui.py',
 'test_dealer_document_queries.py','test_dealer_transactions.py','test_pwa_performance.py',
 'test_sales_ui_contract.py','test_v83_services.py','test_v83_safety.py',
 'test_v83_backup.py','test_v83_templates.py','test_v83_pdf.py',
 'test_v84_purchasing.py','test_v84_routes.py','test_v84_templates.py',
]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres',action='store_true')
    args=parser.parse_args()
    os.chdir(ROOT)
    out=ROOT/'test-results';out.mkdir(exist_ok=True)
    groups=list(BASE_TESTS)
    if args.postgres:
        sys.path.insert(0,str(ROOT))
        from tools.testing_safety import require_test_database
        require_test_database()
        # Missing dependencies must fail, never become skipped acceptance tests.
        import flask, flask_sqlalchemy, flask_login, flask_wtf, flask_compress, psycopg
        groups+=['test_dealer_postgres.py','test_v83_postgres.py','test_v84_postgres.py']
    summaries=[];total=0;skipped=False
    env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    for filename in groups:
        print('Python:',filename,flush=True)
        try:
            result=subprocess.run([sys.executable,'-m','pytest','-q','-o','faulthandler_timeout=30','tests/'+filename],
                cwd=ROOT,env=env,timeout=600 if args.postgres else 120,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        except subprocess.TimeoutExpired:
            print('PENDIENTE: el grupo excedio el tiempo; revisar procesos y dependencias. No se considera aprobado.')
            return 2
        print(result.stdout,flush=True)
        passed=re.search(r'(\d+) passed',result.stdout)
        omitted=re.search(r'(\d+) skipped',result.stdout)
        count=int(passed.group(1)) if passed else 0
        total+=count;skipped=skipped or bool(omitted)
        summaries.append(dict(group=filename,returncode=result.returncode,passed=count,
                              skipped=int(omitted.group(1)) if omitted else 0))
        (out/'cuotago-v83.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
        if result.returncode:return result.returncode
    node=shutil.which('node')
    if node:
        for path in sorted((ROOT/'tests').glob('*.cjs')):
            print('JavaScript:',path.name,flush=True)
            try:
                status=subprocess.run([node,'--test',str(path)],cwd=ROOT,timeout=90).returncode
            except subprocess.TimeoutExpired:
                print('PENDIENTE: prueba JavaScript excedio el tiempo.');return 2
            if status:return status
    else:
        print('PENDIENTE: pruebas JavaScript; no se encontro Node.')
    if skipped:print('PENDIENTE: se omitieron pruebas. Revisar requirements-test.txt y resultados JSON.')
    if not args.postgres:print('PENDIENTE: HTTP/PostgreSQL, bloqueos y concurrencia. Ejecutar con --postgres en base aislada.')
    print(f'{total} pruebas Python registradas. Informe: test-results/cu otago-v83.json'.replace('cu otago','cuotago'))
    return 0 if node and args.postgres and not skipped else 2

if __name__=='__main__':raise SystemExit(main())
