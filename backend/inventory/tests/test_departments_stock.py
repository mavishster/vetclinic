"""Склады отделений (ADR-024): выдача в любой единице, пересчёт — расход, возврат, нормы,
предупреждения, отчёты; склад отделения не виден в общих остатках, счетах и медкарте."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from catalog import services as catalog
from catalog.models import Item, ItemGroup, Kind, Unit
from core import services as core
from core.context import acting_user
from inventory import departments as dept
from inventory import services
from inventory.models import Department, StockDocument, Warehouse
from inventory.services import StockError

D = Decimal
User = get_user_model()


@pytest.fixture
def main(db):
    return Warehouse.objects.get(name="Основной склад")


@pytest.fixture
def surgery(db):
    return Department.objects.get(name="Хирургия")


@pytest.fixture
def pills(main):
    """Таблетки: учёт в таб., упаковка = 8 таб.; на основном складе 10 упак. (80 таб.)."""
    tab, pack = Unit.objects.get(name="таб."), Unit.objects.get(name="упак.")
    item = catalog.save_item(
        Item(kind=Kind.GOODS, name="Мелоксикам", group=ItemGroup.objects.get(name="Расходные материалы"), base_unit=tab),
        [{"unit": tab, "price": D("10")}, {"unit": pack, "ratio": D("8"), "price": D("70"), "barcode": "2000000000024"}],
    )  # fmt: skip
    core.execute_document(services.save_document(
        StockDocument(kind="receipt", warehouse=main),
        [{"item_unit": item.units.get(unit=pack), "quantity": D("10"), "price": D("40"),
          "expiry_date": timezone.localdate() + timedelta(days=300)}],
    ))  # fmt: skip
    return item


def unit(item, name):
    return item.units.get(unit__name=name)


def test_department_has_own_warehouse_hidden_from_general_stock(main, surgery, pills) -> None:
    warehouse = dept.warehouse_of(surgery)

    dept.issue(surgery, [{"item_unit": unit(pills, "упак."), "quantity": D("2")}])

    assert warehouse.kind == Warehouse.Kind.DEPARTMENT
    assert surgery.warehouse == warehouse
    assert services.available(pills, warehouse) == D("16")
    # В общих остатках, счетах, медкарте и выборе склада отделения нет.
    assert services.available(pills) == D("64")
    assert {r["warehouse_name"] for r in services.balances()} == {"Основной склад"}
    assert all(s.warehouse_id != warehouse.pk for s in services.batches_for(pills))
    assert warehouse not in services.visible_warehouses(User(is_superuser=True))
    assert [t["warehouse_name"] for t in services.warehouse_totals()] == ["Основной склад"]


def test_general_documents_cannot_touch_department_warehouse(main, surgery, pills) -> None:
    warehouse = dept.warehouse_of(surgery)

    with pytest.raises(StockError, match="Отделения"):
        services.save_document(
            StockDocument(kind="transfer", warehouse=main, target_warehouse=warehouse),
            [{"item_unit": unit(pills, "таб."), "quantity": D("1")}],
        )
    with pytest.raises(StockError, match="норма"):
        services.set_min_stock(pills, D("5"), warehouse)


def test_issue_in_pieces_count_consumption_and_new_issue_adds_up(main, surgery, pills) -> None:
    nurse = User.objects.create_user(username="nurse", last_name="Петрова", first_name="Анна")
    keeper = User.objects.create_user(username="keeper", last_name="Иванова", first_name="Ольга")
    with acting_user(keeper):
        dept.issue(surgery, [{"item_unit": unit(pills, "упак."), "quantity": D("2")},
                             {"item_unit": unit(pills, "таб."), "quantity": D("4")}])  # fmt: skip
    with acting_user(nurse):
        counted = dept.count(surgery, [{"item_unit": unit(pills, "упак."), "quantity": D("1")},
                                       {"item_unit": unit(pills, "таб."), "quantity": D("2")}])  # fmt: skip
    with acting_user(keeper):
        dept.issue(surgery, [{"item_unit": unit(pills, "упак."), "quantity": D("1")}])

    balance = dept.balances(surgery)
    today = timezone.localdate()
    summary = dept.summary(today, today, surgery)
    journal = dept.journal(today, today, surgery)

    assert counted.kind == "inventory" and counted.department == surgery
    assert [(r["item_name"], r["qty"]) for r in balance] == [("Мелоксикам", D("18"))]  # 10 + 8
    assert services.available(pills, main) == D("52")
    row = summary[0]
    assert (row["issued"], row["consumed"], row["closing"]) == (D("28"), D("10"), D("18"))
    assert row["cost"] == D("50.00")  # 10 таб. × 5 (40 за упак. из 8)
    assert row["not_counted"] is True  # после последней выдачи остатки не вносились
    assert [(j["operation"], j["qty"], j["balance"], j["created_by"]) for j in journal] == [
        ("issue", D("8"), D("18"), "Иванова О."),
        ("consumed", D("-10"), D("10"), "Петрова А."),
        ("issue", D("20"), D("20"), "Иванова О."),
    ]


def test_count_surplus_unchanged_items_and_return(main, surgery, pills) -> None:
    dept.issue(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("10")}])

    dept.count(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("12")}])
    assert dept.balances(surgery)[0]["qty"] == D("12")
    dept.count(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("12")}])  # без изменений
    back = dept.give_back(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("5")}])

    assert back.warehouse == surgery.warehouse and back.target_warehouse == main
    assert dept.balances(surgery)[0]["qty"] == D("7")
    assert services.available(pills, main) == D("75")
    today = timezone.localdate()
    row = dept.summary(today, today, surgery)[0]
    assert (row["surplus"], row["returned"], row["closing"]) == (D("2"), D("5"), D("7"))
    assert row["not_counted"] is False


def test_count_needs_lines_and_rejects_negative(surgery, pills) -> None:
    with pytest.raises(StockError, match="хотя бы"):
        dept.count(surgery, [])
    with pytest.raises(StockError, match="отрицательным"):
        dept.count(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("-1")}])


def test_dates_not_in_future_and_not_before_last_count(surgery, pills) -> None:
    today = timezone.localdate()
    line = [{"item_unit": unit(pills, "таб."), "quantity": D("1")}]

    with pytest.raises(StockError, match="будущем"):
        dept.issue(surgery, line, today + timedelta(days=1))
    dept.issue(surgery, line, today - timedelta(days=3))
    dept.count(surgery, line, today - timedelta(days=1))
    with pytest.raises(StockError, match="пересчёта"):
        dept.issue(surgery, line, today - timedelta(days=2))
    with pytest.raises(StockError, match="последней операции"):
        dept.count(surgery, line, today - timedelta(days=2))
    issued = dept.issue(surgery, line)

    assert issued.date.date() == timezone.localdate()


def test_norms_and_refill_to_norm(surgery, pills) -> None:
    dept.set_norm(surgery, pills, D("24"))
    dept.issue(surgery, [{"item_unit": unit(pills, "упак."), "quantity": D("1")}])

    row = dept.balances(surgery)[0]
    lines = dept.to_norm_lines(surgery)

    assert (row["norm"], row["below_norm"]) == (D("24"), True)
    assert [(r["item_name"], r["need"]) for r in lines] == [("Мелоксикам", D("16"))]
    dept.set_norm(surgery, pills, D("0"))
    assert not dept.norms(surgery).exists()


def test_alerts_follow_clinic_settings_and_go_to_admin_and_responsible(surgery, pills) -> None:
    clinic = core.current_clinic()
    clinic.department_issue_days, clinic.department_count_from_days = 10, 5
    clinic.department_count_due_days = 7
    clinic.save()
    responsible = User.objects.create_user(username="resp")
    surgery.responsible = responsible
    surgery.save()
    admin = User.objects.create_user(username="admin")
    role = Group.objects.create(name="Главный администратор")
    core.set_special_permissions(role, {"inventory.manage_department"})
    admin.groups.add(role)
    other = User.objects.create_user(username="other")
    today = timezone.localdate()
    dept.issue(
        surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("3")}], today - timedelta(days=6)
    )

    def kinds(user, day):
        return sorted(a["kind"] for a in dept.alerts(User.objects.get(pk=user.pk), day))

    assert kinds(admin, today) == ["count_due"]
    assert kinds(responsible, today) == ["count_due"]
    assert kinds(other, today) == []
    assert kinds(admin, today + timedelta(days=1)) == ["count_overdue"]
    assert kinds(admin, today + timedelta(days=4)) == ["count_overdue", "issue_due"]
    dept.count(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("3")}])
    assert kinds(admin, today) == []
    assert dept.status(surgery)["count_pending"] is False


def test_rollback_issue_returns_stock(main, surgery, pills) -> None:
    issued = dept.issue(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("8")}])

    core.rollback_document(issued)

    assert services.available(pills, main) == D("80")
    assert dept.balances(surgery) == []


def test_qty_text_packs_and_pieces(pills) -> None:
    assert catalog.qty_text(pills, D("42")) == "5,25 упак. / 5 упак. 2 таб."
    assert catalog.qty_text(pills, D("16")) == "2 упак."
    assert catalog.qty_text(pills, D("3")) == "0,375 упак. / 3 таб."


# --- API -----------------------------------------------------------------------------


def _client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def test_api_issue_count_reports_and_permissions(main, surgery, pills) -> None:
    admin = _client(User.objects.create_superuser(username="boss", password="x"))
    plain = User.objects.create_user(username="plain")
    role = Group.objects.create(name="Склад")
    core.set_entity_permissions(role, "inventory.stockdocument", {"view", "edit"})
    plain.groups.add(role)
    keeper = _client(User.objects.get(pk=plain.pk))
    pack = str(unit(pills, "упак.").pk)

    lookup = admin.get(f"/api/inventory/stock/lookup/?item={pills.pk}").json()
    issued = keeper.post("/api/inventory/department-stock/issue/", {"department": str(surgery.pk),
                         "date": timezone.localdate().isoformat(), "lines": [{"item_unit": pack, "quantity": "2"}]},
                         format="json")  # fmt: skip
    denied = keeper.post("/api/inventory/department-stock/count/", {"department": str(surgery.pk),
                         "lines": [{"item_unit": pack, "quantity": "1"}]}, format="json")  # fmt: skip
    counted = admin.post("/api/inventory/department-stock/count/", {"department": str(surgery.pk),
                         "lines": [{"item_unit": pack, "quantity": "1.25"}]}, format="json")  # fmt: skip
    balances = admin.get(
        f"/api/inventory/department-stock/balances/?department={surgery.pk}"
    ).json()
    sheet = admin.get(f"/api/inventory/department-stock/sheet/?department={surgery.pk}").json()
    summary = admin.get("/api/inventory/reports/departments/").json()
    journal = admin.get("/api/inventory/reports/department-journal/").json()
    excel = admin.get("/api/inventory/reports/department-journal/?export=xlsx")
    norm = admin.post("/api/inventory/department-stock/norm/", {"department": str(surgery.pk),
                      "item_unit": pack, "quantity": "3"}, format="json")  # fmt: skip
    norm_denied = keeper.post("/api/inventory/department-stock/norm/", {"department": str(surgery.pk),
                              "item_unit": pack, "quantity": "3"}, format="json")  # fmt: skip
    stock = admin.get("/api/inventory/stock/balances/").json()["rows"]
    warehouses = admin.get("/api/inventory/warehouses/").json()

    assert [u["unit_name"] for u in lookup] == ["упак.", "таб."]
    assert issued.status_code == 201, issued.json()
    assert denied.status_code == 403
    assert counted.status_code == 201, counted.json()
    assert balances["rows"][0]["qty_text"] == "1,25 упак. / 1 упак. 2 таб."
    assert balances["totals"][0]["qty"] == "10.000"
    assert [u["unit"] for u in sheet[0]["units"]] == ["упак.", "таб."]
    assert summary[0]["consumed_text"] == "0,75 упак. / 6 таб."
    assert [j["operation"] for j in journal] == ["consumed", "issue"]
    assert excel["Content-Type"].startswith("application/vnd.openxml")
    assert norm.status_code == 200 and norm_denied.status_code == 403
    assert stock[0]["qty_text"] == "8 упак." and stock[0]["warehouse_name"] == "Основной склад"
    assert "Отделение «Хирургия»" not in {w["name"] for w in warehouses}


def test_api_alerts_only_for_admin_or_responsible(surgery, pills) -> None:
    other = _client(User.objects.create_user(username="x"))
    assert other.get("/api/inventory/department-stock/alerts/").json() == []
    assert (
        other.get(f"/api/inventory/department-stock/balances/?department={surgery.pk}").status_code
        == 403
    )


def test_api_count_document_opens_by_link_but_not_in_list(surgery, pills) -> None:
    api = _client(User.objects.create_superuser(username="boss2", password="x"))
    dept.issue(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("4")}])
    counted = dept.count(surgery, [{"item_unit": unit(pills, "таб."), "quantity": D("1")}])

    listed = api.get("/api/inventory/documents/").json()["results"]
    opened = api.get(f"/api/inventory/documents/{counted.pk}/")

    assert str(counted.pk) not in {d["id"] for d in listed}
    assert opened.status_code == 200 and opened.json()["kind"] == "inventory"
