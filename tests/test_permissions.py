from types import SimpleNamespace

from cuotago.permissions import has_permission


def user(role):
    return SimpleNamespace(is_authenticated=True, role=role)


def test_owner_has_all_permissions():
    assert has_permission(user("owner"), "contracts.manage")
    assert has_permission(user("owner"), "backup.export")


def test_collector_can_collect_but_not_reprogram():
    assert has_permission(user("collector"), "collections.collect")
    assert not has_permission(user("collector"), "contracts.manage")
    assert not has_permission(user("collector"), "expenses.manage")


def test_sales_can_create_contract_but_not_see_financial_reports():
    assert has_permission(user("sales"), "contracts.create")
    assert not has_permission(user("sales"), "reports.view")


def test_viewer_is_read_only():
    assert has_permission(user("viewer"), "clients.view")
    assert has_permission(user("viewer"), "reports.view")
    assert not has_permission(user("viewer"), "clients.manage")
    assert not has_permission(user("viewer"), "collections.collect")
