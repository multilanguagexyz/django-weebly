from django.apps import AppConfig
from django.db.models.signals import pre_save, post_save


class WeeblyConfig(AppConfig):
    name = 'weebly'

    def ready(self):
        from weebly.models import WeeblyPaymentNotification
        pre_save.connect(WeeblyPaymentNotification.pre_save, WeeblyPaymentNotification)
