import logging
from django.test import TestCase
from django.utils import timezone
from django.conf import settings
from .models import WeeblyUser, WeeblySite, WeeblyAuth, WeeblyPaymentNotification

logger = logging.getLogger(__name__)


class WeeblyTestCase(TestCase):
    @staticmethod
    def setup_weebly_auth(testcase):
        """
        for testing from another TestCase
        """
        user_id = settings.WEEBLY_TEST['user']
        site_id = settings.WEEBLY_TEST['site']
        site_domain = settings.WEEBLY_TEST['domain']
        auth_token = settings.WEEBLY_TEST['auth_token']

        logger.debug(f'weebly test data: user {user_id} - site {site_id} - {site_domain} - auth {auth_token}')

        testcase.weebly_user = WeeblyUser.objects.create(user_id=user_id,
                                                         name='Martin M',
                                                         email='martinm@email1234.com')
        testcase.weebly_site = WeeblySite.objects.create(site_id=site_id,
                                                         user=testcase.weebly_user,
                                                         site_title='Weebly Developer Test Site',
                                                         domain=site_domain,
                                                         is_published=True)
        testcase.weebly_auth = WeeblyAuth.objects.create(user=testcase.weebly_user,
                                                         site=testcase.weebly_site,
                                                         auth_token=auth_token,
                                                         timestamp=timezone.now())

    def setUp(self):
        WeeblyTestCase.setup_weebly_auth(self)

    def test_refresh(self):
        site = self.weebly_site
        weebly_auth = site.get_default_weebly_auth()

        response_json = [
            {'page_id': '1', 'title': 'page 1', 'page_order': 1, 'parent_id': None, 'layout': 'header', 'page_url': 'page-1.html'},
            {'page_id': '2', 'title': 'page 2', 'page_order': 2, 'parent_id': None, 'layout': 'header', 'page_url': 'page-2.html'},
            {'page_id': '3', 'title': 'page 3', 'page_order': 3, 'parent_id': None, 'layout': 'header', 'page_url': 'page-3.html'},
            {'page_id': '4', 'title': 'page 4', 'page_order': 4, 'parent_id': None, 'layout': 'header', 'page_url': 'page-4.html'},
        ]
        site.refresh_pages_from_data(response_json)
        pages = site.pages.all()
        self.assertEqual(len(pages), 4)
        self.assertEqual(pages[0].page_id, 1)
        self.assertEqual(pages[0].page_order, 1)

        response_json = [
            {'page_id': '1', 'title': 'page 1', 'page_order': 1, 'parent_id': None, 'layout': 'header', 'page_url': 'page-1.html'},
            {'page_id': '2', 'title': 'page 2', 'page_order': 3, 'parent_id': None, 'layout': 'header', 'page_url': 'page-2.html'},
            {'page_id': '3', 'title': 'page 3', 'page_order': 2, 'parent_id': None, 'layout': 'header', 'page_url': 'page-3.html'},
        ]
        site.refresh_pages_from_data(response_json)
        pages = site.pages.all()
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[1].page_id, 2)
        self.assertEqual(pages[1].page_order, 3)

        response_json = [
            {'page_id': '4', 'title': 'page 4', 'page_order': 4, 'parent_id': None, 'layout': 'header', 'page_url': 'page-4.html'},
            {'page_id': '5', 'title': 'page 5', 'page_order': 5, 'parent_id': None, 'layout': 'header', 'page_url': 'page-5.html'},
        ]
        site.refresh_pages_from_data(response_json)
        pages = site.pages.all()
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].page_id, 4)
        self.assertEqual(pages[0].page_order, 4)
        self.assertEqual(pages[1].page_id, 5)
        self.assertEqual(pages[1].page_order, 5)

        site.refresh_pages(weebly_auth)

    def create_payment_notification(self, gross_amount):
        notification = WeeblyPaymentNotification.objects.create(
            site=self.weebly_site,
            name='test payment',
            detail='this is a test payment',
            purchase_not_refund=True,
            kind=WeeblyPaymentNotification.PaymentKind.SETUP,
            term=WeeblyPaymentNotification.PaymentTerm.FOREVER,
            gross_amount=gross_amount
        )
        self.assertEqual(notification.payable_amount, gross_amount * 0.3, 'payable should be 30%')
        self.assertFalse(notification.notified_to_weebly)
        return notification

    def test_payment_notification(self):
        self.assertFalse(settings.PRODUCTION, 'this test can not be run in production')
        logger.info('testing notifying a single payment')
        notification = self.create_payment_notification(10)
        rv = notification.notify()
        self.assertFalse('error' in rv)
        self.assertTrue(notification.notified_to_weebly)

    def test_notify_non_notified(self):
        self.assertFalse(settings.PRODUCTION, 'this test can not be run in production')
        logger.info('testing notify non-notified')
        self.create_payment_notification(10)
        self.create_payment_notification(100)
        self.assertEqual(WeeblyPaymentNotification.objects.filter(notified_to_weebly=False).count(), 2,
                         'There should be non-notified payments')
        WeeblyPaymentNotification.notify_unnotified()
        self.assertEqual(WeeblyPaymentNotification.objects.filter(notified_to_weebly=False).count(), 0,
                         'There should not be any non-notified payments')