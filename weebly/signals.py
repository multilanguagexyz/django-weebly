from django.dispatch import Signal

webhooks_signal = Signal(providing_args=['event', 'weebly_auth', 'client_id', 'client_version', 'timestamp', 'data'])
app_installed_signal = Signal()
site_refreshed_signal = Signal()
