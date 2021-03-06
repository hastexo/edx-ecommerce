"""Order Utility Classes. """
import logging
import random
import string  # pylint: disable=deprecated-module

from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from oscar.core.loading import get_model

logger = logging.getLogger(__name__)

Benefit = get_model('offer', 'Benefit')
Condition = get_model('offer', 'Condition')
ConditionalOffer = get_model('offer', 'ConditionalOffer')
CouponVouchers = get_model('voucher', 'CouponVouchers')
Range = get_model('offer', 'Range')
StockRecord = get_model('partner', 'StockRecord')
Voucher = get_model('voucher', 'Voucher')


def generate_coupon_report(coupon_vouchers):
    """
    Generate coupon report data

    Args:
        coupon_vouchers (List[CouponVouchers]): List of coupon_vouchers the report should be generated for

    Returns:
        List[str]
        List[dict]
    """

    field_names = [_('Name'), _('Code'), _('Discount'), _('URL')]
    rows = []

    for coupon_voucher in coupon_vouchers:
        for voucher in coupon_voucher.vouchers.all():
            offer = voucher.offers.all().first()
            currency = StockRecord.objects.get(product=coupon_voucher.coupon).price_currency
            benefit_value = offer.benefit.value
            if offer.benefit.type == Benefit.PERCENTAGE:
                discount = _("{percentage} %").format(percentage=benefit_value)
            else:
                discount = _("{amount} {currency}").format(amount=benefit_value, currency=currency)
            URL = '{}/coupons/redeem/?code={}'.format(settings.ECOMMERCE_URL_ROOT, voucher.code)
            rows.append({
                'Name': voucher.name,
                'Code': voucher.code,
                'Discount': discount,
                'URL': URL
            })

    return field_names, rows


def _get_or_create_offer(product_range, benefit_type, benefit_value):
    """
    Return an offer for a catalog with condition and benefit.

    If offer doesn't exist, new offer will be created and associated with
    provided Offer condition and benefit.

    Args:
        product_range (Range): Range of products associated with condition
        benefit_type (str): Type of benefit associated with the offer
        benefit_value (Decimal): Value of benefit associated with the offer

    Returns:
        Offer
    """
    offer_condition, __ = Condition.objects.get_or_create(
        range=product_range,
        type=Condition.COUNT,
        value=1,
    )
    offer_benefit, __ = Benefit.objects.get_or_create(
        range=product_range,
        type=benefit_type,
        value=benefit_value,
        max_affected_items=1,
    )

    offer_name = "Catalog [{}]-{}-{}".format(product_range.catalog.id, offer_benefit.type, offer_benefit.value)

    offer, __ = ConditionalOffer.objects.get_or_create(
        name=offer_name,
        offer_type=ConditionalOffer.VOUCHER,
        condition=offer_condition,
        benefit=offer_benefit,
    )
    return offer


def _generate_code_string(length):
    """
    Create a string of random characters of specified length

    Args:
        length (int): Defines the length of randomly generated string

    Raises:
        ValueError raised if length is less than one.

    Returns:
        str
    """
    if length < 1:
        raise ValueError("Voucher code length must be a positive number.")

    chars = [
        char for char in string.ascii_uppercase + string.digits
        if char not in 'AEIOU1'
    ]
    voucher_code = string.join((random.choice(chars) for i in range(length)), '')
    if Voucher.objects.filter(code__iexact=voucher_code).exists():
        return _generate_code_string(length)
    return voucher_code


def _create_new_voucher(code, coupon, end_datetime, name, offer, start_datetime, voucher_type):
    """
    Creates a voucher.

    If randomly generated voucher code already exists, new code will be generated and reverified.

    Args:
        code (str): Code associated with vouchers. If not provided, one will be generated.
        coupon (Product): Coupon product associated with voucher.
        end_datetime (datetime): Voucher end date.
        name (str): Voucher name.
        offer (Offer): Offer associated with voucher.
        start_datetime (datetime): Voucher start date.
        voucher_type (str): Voucher usage.

    Returns:
        Voucher
    """
    voucher_code = code or _generate_code_string(settings.VOUCHER_CODE_LENGTH)

    voucher = Voucher.objects.create(
        name=name,
        code=voucher_code,
        usage=voucher_type,
        start_datetime=start_datetime,
        end_datetime=end_datetime
    )
    voucher.offers.add(offer)

    coupon_voucher, __ = CouponVouchers.objects.get_or_create(coupon=coupon)
    coupon_voucher.vouchers.add(voucher)

    return voucher


def create_vouchers(
        benefit_type,
        benefit_value,
        catalog,
        coupon,
        end_datetime,
        name,
        quantity,
        start_datetime,
        voucher_type,
        code=None):
    """
    Create vouchers

    Args:
            benefit_type (str): Type of benefit associated with vouchers.
            benefit_value (Decimal): Value of benefit associated with vouchers.
            catalog (Catalog): Catalog associated with range of products
                               to which a voucher can be applied to
            coupon (Coupon): Coupon entity associated with vouchers.
            end_datetime (datetime): End date for voucher offer
            name (str): Voucher name
            quantity (int): Number of vouchers to be created.
            start_datetime (datetime): Start date for voucher offer.
            voucher_type (str): Type of voucher.
            code (str): Code associated with vouchers. Defaults to None.

    Returns:
            List[Voucher]
    """

    logger.info("Creating [%d] vouchers catalog [%s]", quantity, catalog.id)

    vouchers = []

    range_name = (_('Range for {catalog_name}').format(catalog_name=catalog.name))
    product_range, __ = Range.objects.get_or_create(
        name=range_name,
        catalog=catalog,
    )

    offer = _get_or_create_offer(
        product_range=product_range,
        benefit_type=benefit_type,
        benefit_value=benefit_value
    )
    for __ in range(quantity):
        voucher = _create_new_voucher(
            coupon=coupon,
            end_datetime=end_datetime,
            offer=offer,
            start_datetime=start_datetime,
            voucher_type=voucher_type,
            code=code,
            name=name
        )
        vouchers.append(voucher)

    return vouchers
