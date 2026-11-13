"""Личные настройки интерфейса: оформление и расклад блоков на экранах."""

from core import services


def test_layouts_are_saved_per_user(db, django_user_model) -> None:
    """Расклад блоков карточки клиента — личный: врач и оператор видят своё."""
    doctor = django_user_model.objects.create_user(username="doc", password="x")

    saved = services.save_ui_settings(
        doctor,
        {
            "layouts": {
                "client": {
                    "preset": "doctor",
                    "blocks": [
                        {"name": "pets", "column": "left", "visible": True},
                        {"name": "invoices", "column": "right", "visible": False},
                    ],
                }
            }
        },
    )

    assert saved["layouts"]["client"]["preset"] == "doctor"
    assert saved["layouts"]["client"]["blocks"][1] == {
        "name": "invoices",
        "column": "right",
        "visible": False,
    }
    doctor.refresh_from_db()
    assert doctor.ui_settings["layouts"]["client"]["blocks"][0]["name"] == "pets"


def test_layouts_are_checked(db, django_user_model) -> None:
    """В настройки попадает только то, что система понимает."""
    user = django_user_model.objects.create_user(username="u", password="x")

    saved = services.save_ui_settings(
        user,
        {
            "layouts": {
                "client": {
                    "blocks": [
                        {"name": "pets", "column": "середина"},  # такого столбца нет
                        {"column": "left"},  # без названия блока
                        "ерунда",
                    ]
                },
                "не идентификатор": {"blocks": []},
            }
        },
    )

    assert list(saved["layouts"]) == ["client"]
    assert saved["layouts"]["client"]["blocks"] == [
        {"name": "pets", "column": "left", "visible": True}
    ]


def test_theme_survives_layout_save(db, django_user_model) -> None:
    user = django_user_model.objects.create_user(username="u2", password="x")
    services.save_ui_settings(user, {"theme": "dark"})

    saved = services.save_ui_settings(user, {"layouts": {"client": {"blocks": []}}})

    assert saved["theme"] == "dark"  # оформление не сбрасывается раскладом
