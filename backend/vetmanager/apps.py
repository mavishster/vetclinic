from django.apps import AppConfig


class VetmanagerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vetmanager"
    verbose_name = "перенос из VetManager"

    def ready(self) -> None:
        from core.events import items_merging
        from vetmanager.models import Imported

        def merge_items(sender, merge, **kwargs):  # type: ignore[no-untyped-def]
            # Связь с VetManager — на основную позицию: повторный перенос счетов найдёт её
            # (единицу строки подберёт по цене), а дубль заново не заведётся.
            links = Imported.objects.filter(
                kind="item", target_id__in=[i.pk for i in merge.items[1:]]
            )
            count = links.count()
            if not merge.dry_run:
                links.update(target_id=merge.main.pk)
            return [("связи с VetManager", count)]

        items_merging.connect(merge_items, weak=False, dispatch_uid="vetmanager_merge_items")
