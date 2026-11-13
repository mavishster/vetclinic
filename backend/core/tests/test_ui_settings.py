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
        "collapsed": False,
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
        {"name": "pets", "column": "left", "visible": True, "collapsed": False}
    ]


def test_theme_survives_layout_save(db, django_user_model) -> None:
    user = django_user_model.objects.create_user(username="u2", password="x")
    services.save_ui_settings(user, {"theme": "dark"})

    saved = services.save_ui_settings(user, {"layouts": {"client": {"blocks": []}}})

    assert saved["theme"] == "dark"  # оформление не сбрасывается раскладом


def test_collapsed_blocks_and_column_width(db, django_user_model) -> None:
    """Свёрнутые блоки и ширина столбцов тоже запоминаются."""
    user = django_user_model.objects.create_user(username="u3", password="x")

    saved = services.save_ui_settings(
        user,
        {
            "layouts": {
                "client": {
                    "leftWidth": 7,
                    "blocks": [{"name": "visits", "column": "right", "collapsed": True}],
                }
            }
        },
    )

    assert saved["layouts"]["client"]["leftWidth"] == 7
    assert saved["layouts"]["client"]["blocks"][0]["collapsed"] is True


def test_strange_width_falls_back(db, django_user_model) -> None:
    user = django_user_model.objects.create_user(username="u4", password="x")

    saved = services.save_ui_settings(
        user, {"layouts": {"client": {"leftWidth": 99, "blocks": []}}}
    )

    assert saved["layouts"]["client"]["leftWidth"] == 5  # столбец во весь экран не делаем
