from __future__ import unicode_literals

import datetime
import json

from django.core.urlresolvers import reverse
from django.db.utils import IntegrityError
from django.test import RequestFactory
from oscar.core.loading import get_model

from ecommerce.core.models import Client
from ecommerce.extensions.api.constants import APIConstants as AC
from ecommerce.extensions.api.v2.views.coupons import CouponOrderCreateView
from ecommerce.tests.factories import SiteFactory, SiteConfigurationFactory
from ecommerce.tests.testcases import TestCase

Basket = get_model('basket', 'Basket')
Benefit = get_model('offer', 'Benefit')
Catalog = get_model('catalogue', 'Catalog')
Course = get_model('courses', 'Course')
Order = get_model('order', 'Order')
Product = get_model('catalogue', 'Product')
ProductClass = get_model('catalogue', 'ProductClass')
StockRecord = get_model('partner', 'StockRecord')
Voucher = get_model('voucher', 'Voucher')

COUPONS_CREATE = reverse('api:v2:coupons:create')
PRODUCTS_LIST = reverse('api:v2:product-list')


class CouponOrderCreateViewTest(TestCase):
    """Unit tests for creating coupon order."""

    def setUp(self):
        super(CouponOrderCreateViewTest, self).setUp()
        self.user = self.create_user(is_staff=True)
        self.client.login(username=self.user.username, password=self.password)

        course_id = 'edx/Demo_Course/DemoX'
        course = Course.objects.create(id=course_id)
        course.create_or_update_seat('verified', True, 50, self.partner)

        self.catalog = Catalog.objects.create(partner=self.partner)
        self.product_class, __ = ProductClass.objects.get_or_create(name='Coupon')

    def create_coupon(self, title, price, data=None):
        """Helper method for creating a coupon."""
        if data is None:
            # Use default values
            data = {
                'partner': self.partner,
                'benefit_type': Benefit.PERCENTAGE,
                'benefit_value': 100,
                'catalog': self.catalog,
                'end_date': datetime.date(2020, 1, 1),
                'code': '',
                'quantity': 5,
                'start_date': datetime.date(2015, 1, 1),
                'voucher_type': Voucher.SINGLE_USE
            }

        coupon = CouponOrderCreateView().create_coupon_product(
            title=title,
            price=price,
            data=data
        )
        return coupon

    def test_list_coupons(self):
        """Test coupon API endpoint list."""
        self.create_coupon(title='Test coupon', price=100)

        response = self.client.get(PRODUCTS_LIST)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)['results']
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['price'], '100.00')
        self.assertEqual(result[0]['attribute_values'][0]['name'], 'Coupon vouchers')
        self.assertEqual(len(result[0]['attribute_values'][0]['value']), 5)

    def test_create(self):
        """Test the create method."""
        site_configuration = SiteConfigurationFactory(partner__name='TestX')
        site = SiteFactory()
        site.siteconfiguration = site_configuration
        data = {
            'title': 'Test coupon',
            'client_username': 'Client',
            'stock_record_ids': [1],
            'start_date': '2015-1-1',
            'end_date': '2020-1-1',
            'code': '',
            'benefit_type': Benefit.PERCENTAGE,
            'benefit_value': 100,
            'voucher_type': Voucher.SINGLE_USE,
            'quantity': 1,
            'price': 100
        }
        request = RequestFactory()
        request.data = data
        request.site = site

        response = CouponOrderCreateView().create(request)

        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(
            response.data,
            {u'payment_data': {u'payment_processor_name': u'Invoice'}, u'id': 1, u'order': 1}
        )

    def test_create_coupon_product(self):
        """Test the created coupon data."""
        coupon = self.create_coupon(title='Test coupon', price=100)
        self.assertEqual(Product.objects.filter(product_class=self.product_class).count(), 1)
        self.assertIsInstance(coupon, Product)
        self.assertEqual(coupon.title, 'Test coupon')

        self.assertEqual(StockRecord.objects.filter(product=coupon).count(), 1)
        stock_record = StockRecord.objects.get(product=coupon)
        self.assertEqual(stock_record.price_currency, 'USD')
        self.assertEqual(stock_record.price_excl_tax, 100)

        self.assertEqual(coupon.attr.coupon_vouchers.vouchers.count(), 5)

    def test_append_to_existing_coupon(self):
        """Test adding additional vouchers to an existing coupon."""
        self.create_coupon(title='Test coupon', price=100)
        data = {
            'partner': self.partner,
            'benefit_type': Benefit.PERCENTAGE,
            'benefit_value': 50,
            'catalog': self.catalog,
            'end_date': datetime.date(2020, 1, 1),
            'code': '',
            'quantity': 2,
            'start_date': datetime.date(2015, 1, 1),
            'voucher_type': Voucher.MULTI_USE
        }
        coupon_append = CouponOrderCreateView().create_coupon_product(
            title='Test coupon',
            price=100,
            data=data
        )

        self.assertEqual(Product.objects.filter(product_class=self.product_class).count(), 1)
        self.assertEqual(StockRecord.objects.filter(product=coupon_append).count(), 1)
        self.assertEqual(coupon_append.attr.coupon_vouchers.vouchers.count(), 7)
        self.assertEqual(coupon_append.attr.coupon_vouchers.vouchers.filter(usage=Voucher.MULTI_USE).count(), 2)

    def test_custom_code_string(self):
        """Test creating a coupon with custom voucher code."""
        data = {
            'partner': self.partner,
            'benefit_type': Benefit.PERCENTAGE,
            'benefit_value': 100,
            'catalog': self.catalog,
            'end_date': datetime.date(2020, 1, 1),
            'code': 'CUSTOMCODE',
            'quantity': 1,
            'start_date': datetime.date(2015, 1, 1),
            'voucher_type': Voucher.ONCE_PER_CUSTOMER
        }
        custom_coupon = CouponOrderCreateView().create_coupon_product(
            title='Custom coupon',
            price=100,
            data=data
        )
        self.assertEqual(custom_coupon.attr.coupon_vouchers.vouchers.count(), 1)
        self.assertEqual(custom_coupon.attr.coupon_vouchers.vouchers.first().code, 'CUSTOMCODE')

    def test_custom_code_integrity_error(self):
        """Test custom coupon code duplication."""
        data = {
            'partner': self.partner,
            'benefit_type': Benefit.PERCENTAGE,
            'benefit_value': 100,
            'catalog': self.catalog,
            'end_date': datetime.date(2020, 1, 1),
            'code': 'CUSTOMCODE',
            'quantity': 1,
            'start_date': datetime.date(2015, 1, 1),
            'voucher_type': Voucher.SINGLE_USE
        }
        CouponOrderCreateView().create_coupon_product(
            title='Custom coupon',
            price=100,
            data=data
        )

        with self.assertRaises(IntegrityError):
            CouponOrderCreateView().create_coupon_product(
                title='Coupon with integrity issue',
                price=100,
                data=data
            )

    def test_add_product_to_basket(self):
        """Test adding a coupon product to a basket."""
        coupon = self.create_coupon(title='Test coupon', price=100)
        coupon_client = Client.objects.create(username='TestX')
        basket = CouponOrderCreateView().add_product_to_basket(
            product=coupon,
            client=coupon_client,
            site=self.site,
            partner=self.partner
        )

        self.assertIsInstance(basket, Basket)
        self.assertEqual(Basket.objects.count(), 1)
        self.assertEqual(basket.lines.count(), 1)
        self.assertEqual(basket.lines.first().price_excl_tax, 100)

    def test_create_order(self):
        """Test the order creation."""
        coupon = self.create_coupon(title='Test coupon', price=100)
        coupon_client = Client.objects.create(username='TestX')
        basket = CouponOrderCreateView().add_product_to_basket(
            product=coupon,
            client=coupon_client,
            site=self.site,
            partner=self.partner
        )
        response_data = CouponOrderCreateView().create_order_for_invoice(basket)
        self.assertEqual(response_data[AC.KEYS.BASKET_ID], 1)
        self.assertEqual(response_data[AC.KEYS.ORDER], 1)
        self.assertEqual(response_data[AC.KEYS.PAYMENT_DATA][AC.KEYS.PAYMENT_PROCESSOR_NAME], 'Invoice')

        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.first().status, 'Complete')
        self.assertEqual(Order.objects.first().total_incl_tax, 100)
        self.assertEqual(Basket.objects.first().status, 'Submitted')


class CouponOrderCreateViewFunctionalTest(TestCase):
    """Test the coupon order creation functionality."""

    def setUp(self):
        super(CouponOrderCreateViewFunctionalTest, self).setUp()
        self.user = self.create_user(is_staff=True)
        self.client.login(username=self.user.username, password=self.password)

        course_id = 'edx/Demo_Course/DemoX'
        course = Course.objects.create(id=course_id)
        course.create_or_update_seat('verified', True, 50, self.partner)

        course_id = 'edx/Demo_Course2/DemoX'
        course = Course.objects.create(id=course_id)
        course.create_or_update_seat('verified', True, 100, self.partner)

        data = {
            'title': 'Test coupon',
            'client_username': 'TestX',
            'stock_record_ids': [1, 2],
            'start_date': '2015-01-01',
            'end_date': '2020-01-01',
            'code': '',
            'benefit_type': Benefit.PERCENTAGE,
            'benefit_value': 100,
            'voucher_type': Voucher.SINGLE_USE,
            'quantity': 2,
            'price': 100
        }
        self.response = self.client.post(COUPONS_CREATE, data, format='json')

    def test_response(self):
        """Test the response data given after the order was created."""
        self.assertEqual(self.response.status_code, 200)
        response_data = json.loads(self.response.content)
        self.assertEqual(response_data[AC.KEYS.BASKET_ID], 1)
        self.assertEqual(response_data[AC.KEYS.ORDER], 1)
        self.assertEqual(response_data[AC.KEYS.PAYMENT_DATA][AC.KEYS.PAYMENT_PROCESSOR_NAME], 'Invoice')

    def test_order(self):
        """Test the order data after order creation."""
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.first().status, 'Complete')
        self.assertEqual(Order.objects.first().lines.count(), 1)
        self.assertEqual(Order.objects.first().lines.first().product.title, 'Test coupon')