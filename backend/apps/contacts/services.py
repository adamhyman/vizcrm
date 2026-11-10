from django.db.models import Q

from .models import phone_digits

# Shorter digit strings match too many numbers to be useful.
MIN_PHONE_SEARCH_DIGITS = 3


def search_customers(queryset, text):
    """Filter customers by phone (any part of the number) or by name / email.

    Text that is only a phone number — digits plus spaces, dashes, dots, brackets or a
    leading + — searches phone numbers. Otherwise every word must match the first
    name, last name or email.
    """
    text = text.strip()
    digits = phone_digits(text)
    if len(digits) >= MIN_PHONE_SEARCH_DIGITS and not set(text) - set('0123456789 -.()+'):
        return queryset.filter(phone_digits__contains=digits)
    for word in text.split():
        queryset = queryset.filter(
            Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(email__icontains=word)
        )
    return queryset
