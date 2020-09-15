import logging
from django.core.management.base import BaseCommand
from weebly.models import WeeblyPaymentNotification

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Notifies all un-notified payments'

    def handle(self, *args, **options):
        WeeblyPaymentNotification.notify_unnotified()
