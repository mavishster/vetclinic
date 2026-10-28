"""События ядра (PROJECT_PLAN 4.3, правило 3).

Модули подписываются на события, чтобы реагировать на действия других модулей,
не зная о них. Получатели выполняются в той же транзакции: ошибка в получателе
отменяет всю операцию (так работают деньги и остатки). Уведомления и выгрузку
в облако получатель откладывает сам через transaction.on_commit().

    @receiver(document_executed, sender=Invoice)
    def write_off_stock(sender, document, **kwargs): ...
"""

from django.dispatch import Signal

document_executed = Signal()  # аргументы: document
document_rolled_back = Signal()  # аргументы: document
