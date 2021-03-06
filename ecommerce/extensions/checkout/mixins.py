# Note: If future versions of django-oscar include new mixins, they will need to be imported here.
import abc

from django.db import transaction
from ecommerce_worker.fulfillment.v1.tasks import fulfill_order
from oscar.apps.checkout.mixins import OrderPlacementMixin
from oscar.core.loading import get_class
import waffle

from ecommerce.extensions.analytics.utils import audit_log


post_checkout = get_class('checkout.signals', 'post_checkout')


class EdxOrderPlacementMixin(OrderPlacementMixin):
    """ Mixin for edX-specific order placement. """

    # Instance of a payment processor with which to handle payment. Subclasses should set this value.
    payment_processor = None

    order_placement_failure_msg = 'Payment was received, but an order for basket [%d] could not be placed.'

    __metaclass__ = abc.ABCMeta

    def add_payment_event(self, event):  # pylint: disable = arguments-differ
        """ Record a payment event for creation once the order is placed. """
        if self._payment_events is None:
            self._payment_events = []
        self._payment_events.append(event)

    def handle_payment(self, response, basket):
        """
        Handle any payment processing and record payment sources and events.

        This method is responsible for handling payment and recording the
        payment sources (using the add_payment_source method) and payment
        events (using add_payment_event) so they can be
        linked to the order when it is saved later on.
        """
        source, payment_event = self.payment_processor.handle_processor_response(response, basket=basket)

        self.add_payment_source(source)
        self.add_payment_event(payment_event)

        audit_log(
            'payment_received',
            amount=payment_event.amount,
            basket_id=basket.id,
            currency=source.currency,
            processor_name=payment_event.processor_name,
            reference=payment_event.reference,
            user_id=basket.owner.id
        )

    def handle_order_placement(self,
                               order_number,
                               user,
                               basket,
                               shipping_address,
                               shipping_method,
                               shipping_charge,
                               billing_address,
                               order_total,
                               **kwargs):
        """
        Place an order and mark the corresponding basket as submitted.

        Differs from the superclass' method by wrapping order placement
        and basket submission in a transaction. Should be used only in
        the context of an exception handler.
        """
        with transaction.atomic():
            order = self.place_order(
                order_number=order_number,
                user=user,
                basket=basket,
                shipping_address=shipping_address,
                shipping_method=shipping_method,
                shipping_charge=shipping_charge,
                order_total=order_total,
                billing_address=billing_address,
                **kwargs
            )

            basket.submit()

        return self.handle_successful_order(order)

    def handle_successful_order(self, order):
        """Send a signal so that receivers can perform relevant tasks (e.g., fulfill the order)."""
        audit_log(
            'order_placed',
            amount=order.total_excl_tax,
            basket_id=order.basket.id,
            currency=order.currency,
            order_number=order.number,
            user_id=order.user.id
        )

        if waffle.sample_is_active('async_order_fulfillment'):
            # Always commit transactions before sending tasks depending on state from the current transaction!
            # There's potential for a race condition here if the task starts executing before the active
            # transaction has been committed; the necessary order doesn't exist in the database yet.
            # See http://celery.readthedocs.org/en/latest/userguide/tasks.html#database-transactions.
            fulfill_order.delay(order.number)
        else:
            post_checkout.send(sender=self, order=order)

        return order
