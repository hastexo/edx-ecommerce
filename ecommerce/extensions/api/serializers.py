"""Serializers for data manipulated by ecommerce API endpoints."""
from decimal import Decimal
import logging

from dateutil.parser import parse
from django.db import transaction
from django.utils.translation import ugettext_lazy as _
from oscar.core.loading import get_model, get_class
from rest_framework import serializers
from rest_framework.reverse import reverse
import waffle

from ecommerce.core.constants import ISO_8601_FORMAT, COURSE_ID_REGEX
from ecommerce.courses.models import Course


logger = logging.getLogger(__name__)

Basket = get_model('basket', 'Basket')
Benefit = get_model('offer', 'Benefit')
BillingAddress = get_model('order', 'BillingAddress')
Catalog = get_model('catalogue', 'Catalog')
Line = get_model('order', 'Line')
Order = get_model('order', 'Order')
Product = get_model('catalogue', 'Product')
Partner = get_model('partner', 'Partner')
ProductAttributeValue = get_model('catalogue', 'ProductAttributeValue')
Refund = get_model('refund', 'Refund')
Selector = get_class('partner.strategy', 'Selector')
StockRecord = get_model('partner', 'StockRecord')
Voucher = get_model('voucher', 'Voucher')

COURSE_DETAIL_VIEW = 'api:v2:course-detail'
PRODUCT_DETAIL_VIEW = 'api:v2:product-detail'


class ProductPaymentInfoMixin(serializers.ModelSerializer):
    """ Mixin class used for retrieving price information from products. """
    price = serializers.SerializerMethodField()

    def get_price(self, product):
        info = self._get_info(product)
        if info.availability.is_available_to_buy:
            return serializers.DecimalField(max_digits=10, decimal_places=2).to_representation(info.price.excl_tax)
        return None

    def _get_info(self, product):
        return Selector().strategy(
            request=self.context.get('request')
        ).fetch_for_product(product)


class BillingAddressSerializer(serializers.ModelSerializer):
    """Serializes a Billing Address. """
    city = serializers.CharField(max_length=255, source='line4')

    class Meta(object):
        model = BillingAddress
        fields = ('first_name', 'last_name', 'line1', 'line2', 'postcode', 'state', 'country', 'city')


class ProductAttributeValueSerializer(serializers.ModelSerializer):
    """ Serializer for ProductAttributeValue objects. """
    name = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()

    def get_name(self, instance):
        return instance.attribute.name

    def get_value(self, obj):
        if obj.attribute.name == 'Coupon vouchers':
            request = self.context.get('request')
            vouchers = obj.value.vouchers.all()
            serializer = VoucherSerializer(vouchers, many=True, context={'request': request})
            return serializer.data
        return obj.value

    class Meta(object):
        model = ProductAttributeValue
        fields = ('name', 'value',)


class StockRecordSerializer(serializers.ModelSerializer):
    """ Serializer for stock record objects. """

    class Meta(object):
        model = StockRecord
        fields = ('id', 'product', 'partner', 'partner_sku', 'price_currency', 'price_excl_tax',)


class PartialStockRecordSerializerForUpdate(StockRecordSerializer):
    """ Stock record objects serializer for PUT requests.

    Allowed fields to update are 'price_currency' and 'price_excl_tax'.
    """

    class Meta(object):
        model = StockRecord
        fields = ('price_currency', 'price_excl_tax',)


class ProductSerializer(ProductPaymentInfoMixin, serializers.HyperlinkedModelSerializer):
    """ Serializer for Products. """
    attribute_values = serializers.SerializerMethodField()
    product_class = serializers.SerializerMethodField()
    is_available_to_buy = serializers.SerializerMethodField()
    stockrecords = StockRecordSerializer(many=True, read_only=True)

    def get_attribute_values(self, product):
        request = self.context.get('request')
        attributes = product.attr
        serializer = ProductAttributeValueSerializer(
            attributes,
            many=True,
            read_only=True,
            context={'request': request}
        )
        return serializer.data

    def get_product_class(self, product):
        return product.get_product_class().name

    def get_is_available_to_buy(self, product):
        info = self._get_info(product)
        return info.availability.is_available_to_buy

    class Meta(object):
        model = Product
        fields = ('id', 'url', 'structure', 'product_class', 'title', 'price', 'expires', 'attribute_values',
                  'is_available_to_buy', 'stockrecords',)
        extra_kwargs = {
            'url': {'view_name': PRODUCT_DETAIL_VIEW},
        }


class LineSerializer(serializers.ModelSerializer):
    """Serializer for parsing line item data."""
    product = ProductSerializer()

    class Meta(object):
        model = Line
        fields = ('title', 'quantity', 'description', 'status', 'line_price_excl_tax', 'unit_price_excl_tax', 'product')


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for parsing order data."""
    date_placed = serializers.DateTimeField(format=ISO_8601_FORMAT)
    lines = LineSerializer(many=True)
    billing_address = BillingAddressSerializer(allow_null=True)

    class Meta(object):
        model = Order
        fields = ('number', 'date_placed', 'status', 'currency', 'total_excl_tax', 'lines', 'billing_address')


class PaymentProcessorSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """ Serializer to use with instances of processors.BasePaymentProcessor """

    def to_representation(self, instance):
        """ Serialize instances as a string instead of a mapping object. """
        return instance.NAME


class RefundSerializer(serializers.ModelSerializer):
    """ Serializer for Refund objects. """

    class Meta(object):
        model = Refund


class CourseSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.RegexField(COURSE_ID_REGEX, max_length=255)
    products = ProductSerializer(many=True)
    products_url = serializers.SerializerMethodField()
    last_edited = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super(CourseSerializer, self).__init__(*args, **kwargs)

        include_products = kwargs['context'].pop('include_products', False)
        if not include_products:
            self.fields.pop('products', None)

    def get_last_edited(self, obj):
        return obj.history.latest().history_date.strftime(ISO_8601_FORMAT)

    def get_products_url(self, obj):
        return reverse('api:v2:course-product-list', kwargs={'parent_lookup_course_id': obj.id},
                       request=self.context['request'])

    class Meta(object):
        model = Course
        fields = ('id', 'url', 'name', 'verification_deadline', 'type', 'products_url', 'last_edited', 'products')
        read_only_fields = ('type', 'products')
        extra_kwargs = {
            'url': {'view_name': COURSE_DETAIL_VIEW}
        }


class AtomicPublicationSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Serializer for saving and publishing a Course and associated products.

    Using a ModelSerializer for the Course data makes it difficult to use this serializer to handle updates.
    The automatically applied validation logic rejects course IDs which already exist in the database.
    """
    id = serializers.RegexField(COURSE_ID_REGEX, max_length=255)
    name = serializers.CharField(max_length=255)
    # Verification deadline should only be required if the course actually requires verification.
    verification_deadline = serializers.DateTimeField(required=False, allow_null=True)
    products = serializers.ListField()

    def __init__(self, *args, **kwargs):
        super(AtomicPublicationSerializer, self).__init__(*args, **kwargs)

        self.access_token = kwargs['context'].pop('access_token')
        self.partner = kwargs['context'].pop('partner', None)

    def validate_products(self, products):
        """Validate product data."""
        for product in products:
            # Verify that each product is intended to be a Seat.
            product_class = product.get('product_class')
            if product_class != 'Seat':
                raise serializers.ValidationError(
                    _(u"Invalid product class [{product_class}] requested.".format(product_class=product_class))
                )

            # Verify that attributes required to create a Seat are present.
            attrs = self._flatten(product['attribute_values'])
            if attrs.get('id_verification_required') is None:
                raise serializers.ValidationError(_(u"Products must indicate whether ID verification is required."))

            # Verify that a price is present.
            if product.get('price') is None:
                raise serializers.ValidationError(_(u"Products must have a price."))

        return products

    def get_partner(self):
        """Validate partner"""
        if not self.partner:
            partner = Partner.objects.get(id=1)
            return partner

        return self.partner

    def save(self):
        """Save and publish Course and associated products."

        Returns:
            tuple: A Boolean indicating whether the Course was created, an Exception,
                if one was raised (else None), and a message for the user, if necessary (else None).
        """
        course_id = self.validated_data['id']
        course_name = self.validated_data['name']
        course_verification_deadline = self.validated_data.get('verification_deadline')
        products = self.validated_data['products']
        partner = self.get_partner()

        try:
            if not waffle.switch_is_active('publish_course_modes_to_lms'):
                message = _(
                    u'Course [{course_id}] was not published to LMS '
                    u'because the switch [publish_course_modes_to_lms] is disabled. '
                    u'To avoid ghost SKUs, data has not been saved.'
                ).format(course_id=course_id)

                raise Exception(message)

            # Explicitly delimit operations which will be rolled back if an exception is raised.
            with transaction.atomic():
                course, created = Course.objects.get_or_create(id=course_id)
                course.name = course_name
                course.verification_deadline = course_verification_deadline
                course.save()

                for product in products:
                    attrs = self._flatten(product['attribute_values'])

                    # Extract arguments required for Seat creation, deserializing as necessary.
                    certificate_type = attrs.get('certificate_type', '')
                    id_verification_required = attrs['id_verification_required']
                    price = Decimal(product['price'])

                    # Extract arguments which are optional for Seat creation, deserializing as necessary.
                    expires = product.get('expires')
                    expires = parse(expires) if expires else None
                    credit_provider = attrs.get('credit_provider')
                    credit_hours = attrs.get('credit_hours')
                    credit_hours = int(credit_hours) if credit_hours else None

                    course.create_or_update_seat(
                        certificate_type,
                        id_verification_required,
                        price,
                        partner,
                        expires=expires,
                        credit_provider=credit_provider,
                        credit_hours=credit_hours,
                    )

                resp_message = course.publish_to_lms(access_token=self.access_token)
                published = (resp_message is None)

                if published:
                    return created, None, None
                else:
                    raise Exception(resp_message)

        except Exception as e:  # pylint: disable=broad-except
            logger.exception(u'Failed to save and publish [%s]: [%s]', course_id, e.message)
            return False, e, e.message

    def _flatten(self, attrs):
        """Transform a list of attribute names and values into a dictionary keyed on the names."""
        return {attr['name']: attr['value'] for attr in attrs}


class PartnerSerializer(serializers.ModelSerializer):
    """Serializer for the Partner object"""
    catalogs = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    def get_products(self, obj):
        return reverse(
            'api:v2:partner-product-list',
            kwargs={'parent_lookup_stockrecords__partner_id': obj.id},
            request=self.context['request']
        )

    def get_catalogs(self, obj):
        return reverse(
            'api:v2:partner-catalogs-list',
            kwargs={'parent_lookup_partner_id': obj.id},
            request=self.context['request']
        )

    class Meta(object):
        model = Partner
        fields = ('id', 'name', 'short_code', 'catalogs', 'products')


class CatalogSerializer(serializers.ModelSerializer):
    """ Serializer for Catalogs. """

    products = serializers.SerializerMethodField()

    class Meta(object):
        model = Catalog
        fields = ('id', 'partner', 'name', 'products')

    def get_products(self, obj):
        return reverse(
            'api:v2:catalog-product-list',
            kwargs={'parent_lookup_stockrecords__catalogs': obj.id},
            request=self.context['request']
        )


class VoucherSerializer(serializers.ModelSerializer):
    is_available_to_user = serializers.SerializerMethodField()
    benefit = serializers.SerializerMethodField()

    def get_is_available_to_user(self, obj):
        request = self.context.get('request')
        return obj.is_available_to_user(user=request.user)

    def get_benefit(self, obj):
        return (obj.offers.first().benefit.type, obj.offers.first().benefit.value)

    class Meta(object):
        model = Voucher
        fields = (
            'id', 'name', 'code', 'usage', 'start_datetime', 'end_datetime',
            'num_basket_additions', 'num_orders', 'total_discount',
            'date_created', 'offers', 'is_available_to_user', 'benefit'
        )


class CouponSerializer(ProductPaymentInfoMixin, serializers.ModelSerializer):
    """ Serializer for Coupons. """
    coupon_type = serializers.SerializerMethodField()
    last_edited = serializers.SerializerMethodField()
    catalog = serializers.SerializerMethodField()
    client = serializers.SerializerMethodField()
    vouchers = serializers.SerializerMethodField()

    def get_coupon_type(self, obj):
        voucher = obj.attr.coupon_vouchers.vouchers.first()
        benefit = voucher.offers.first().benefit
        if benefit.type == Benefit.PERCENTAGE and benefit.value == 100:
            return "Enrollment code"
        return "Discount code"

    def get_last_edited(self, obj):
        history = obj.history.latest()
        if history.history_user:
            return (obj.history.latest().history_user.username, obj.history.latest().history_date)
        return []

    def get_catalog(self, obj):
        voucher = obj.attr.coupon_vouchers.vouchers.first()
        catalog = voucher.offers.first().condition.range.catalog
        serializer = CatalogSerializer(catalog, context={'request': self.context['request']})
        return serializer.data

    def get_client(self, obj):
        return Basket.objects.get(lines__product_id=obj.id).owner.username

    def get_vouchers(self, obj):
        vouchers = obj.attr.coupon_vouchers.vouchers.all()
        serializer = VoucherSerializer(vouchers, many=True, context={'request': self.context['request']})
        return serializer.data

    class Meta(object):
        model = Product
        fields = ('id', 'title', 'coupon_type', 'last_edited', 'catalog', 'client', 'price', 'vouchers')
