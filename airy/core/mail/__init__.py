"""
Tools for sending email.
"""

from airy.core.conf import settings
from airy.core.exceptions import ImproperlyConfigured
from airy.utils.importlib import import_module

# Imported for backwards compatibility, and for the sake
# of a cleaner namespace. These symbols used to be in
# django/core/mail.py before the introduction of email
# backends and the subsequent reorganization (See #10355)
from airy.core.mail.utils import CachedDnsName, DNS_NAME
from airy.core.mail.message import (
    EmailMessage, EmailMultiAlternatives,
    SafeMIMEText, SafeMIMEMultipart,
    DEFAULT_ATTACHMENT_MIME_TYPE, make_msgid,
    BadHeaderError, forbid_multi_line_headers)


def get_connection(backend=None, fail_silently=False, **kwds):
    """Load an email backend and return an instance of it.

    If backend is None (default) settings.EMAIL_BACKEND is used.

    Both fail_silently and other keyword arguments are used in the
    constructor of the backend.
    """
    path = backend or settings.email_backend
    try:
        mod_name, klass_name = path.rsplit('.', 1)
        mod = import_module(mod_name)
    except ImportError, e:
        raise ImproperlyConfigured(('Error importing email backend module %s: "%s"'
                                    % (mod_name, e)))
    try:
        klass = getattr(mod, klass_name)
    except AttributeError:
        raise ImproperlyConfigured(('Module "%s" does not define a '
                                    '"%s" class' % (mod_name, klass_name)))
    return klass(fail_silently=fail_silently, **kwds)


def send_mail(subject, message, from_email, recipient_list,
              fail_silently=False, auth_user=None, auth_password=None,
              connection=None):
    """
    Easy wrapper for sending a single message to a recipient list. All members
    of the recipient list will see the other recipients in the 'To' field.

    If auth_user is None, the EMAIL_HOST_USER setting is used.
    If auth_password is None, the EMAIL_HOST_PASSWORD setting is used.

    Note: The API for this method is frozen. New code wanting to extend the
    functionality should use the EmailMessage class directly.
    """
    connection = connection or get_connection(username=auth_user,
                                    password=auth_password,
                                    fail_silently=fail_silently)
    return EmailMessage(subject, message, from_email, recipient_list,
                        connection=connection).send()


def send_mail_multipart(subject, message, from_email, recipient_list,
                        fail_silently=False, connection=None,
                        html_message=None, attachments=[]):
    """Sends a multipart message."""
    if not settings.ADMINS:
        return
    mail = EmailMultiAlternatives(subject,
        message, from_email, recipient_list,
        connection=connection)
    if html_message:
        mail.attach_alternative(html_message, 'text/html')
    for filepath in attachments:
        mail.attach_file(filepath)
    mail.send(fail_silently=fail_silently)


def send_mass_mail(datatuple, fail_silently=False, auth_user=None,
                   auth_password=None, connection=None):
    """
    Given a datatuple of (subject, message, from_email, recipient_list), sends
    each message to each recipient list. Returns the number of emails sent.

    If from_email is None, the DEFAULT_FROM_EMAIL setting is used.
    If auth_user and auth_password are set, they're used to log in.
    If auth_user is None, the EMAIL_HOST_USER setting is used.
    If auth_password is None, the EMAIL_HOST_PASSWORD setting is used.

    Note: The API for this method is frozen. New code wanting to extend the
    functionality should use the EmailMessage class directly.
    """
    connection = connection or get_connection(username=auth_user,
                                    password=auth_password,
                                    fail_silently=fail_silently)
    messages = [EmailMessage(subject, message, sender, recipient,
                             connection=connection)
                for subject, message, sender, recipient in datatuple]
    return connection.send_messages(messages)


def mail_admins(subject, message, fail_silently=False, connection=None,
                html_message=None):
    """Sends a message to the admins, as defined by the ADMINS setting."""
    if not settings.ADMINS:
        return
    mail = EmailMultiAlternatives(u'%s%s' % (settings.email_subject_prefix, subject),
                message, settings.server_email, [a[1] for a in settings.admins],
                connection=connection)
    if html_message:
        mail.attach_alternative(html_message, 'text/html')
    mail.send(fail_silently=fail_silently)


def mail_managers(subject, message, fail_silently=False, connection=None,
                  html_message=None):
    """Sends a message to the managers, as defined by the MANAGERS setting."""
    if not settings.MANAGERS:
        return
    mail = EmailMultiAlternatives(u'%s%s' % (settings.email_subject_prefix, subject),
                message, settings.server_email, [a[1] for a in settings.managers],
                connection=connection)
    if html_message:
        mail.attach_alternative(html_message, 'text/html')
    mail.send(fail_silently=fail_silently)
