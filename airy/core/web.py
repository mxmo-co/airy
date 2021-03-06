import calendar
from airy.core.conf import settings
from airy.core.exceptions import Http404
from airy.core.files.uploadedfile import SimpleUploadedFile
from airy.core.reportbug import report_on_fail
from airy.utils.encoding import smart_unicode
from airy.utils.functional import curry
from tornado.web import *
from tornado.escape import *
from tornadio2 import TornadioRouter, SocketConnection, event
from urlparse import urlparse, parse_qs
from urllib2 import unquote
import logging
import base64


class ConnectionSet(set):
    """
    A set of all active connections
    """

    def _get_filter_condition(self, item, key, value):
        try:
            key, tester = key.split('__', 1)
        except ValueError:
            tester = None
        if tester:
            if callable(getattr(getattr(item, key), tester)):
                condition = getattr(getattr(item, key), tester)(value)
            else:
                condition = getattr(getattr(item, key), tester) == value
        else:
            condition = getattr(item, key) == value
        return condition

    def filter(self, **kwargs):
        filtered_set = ConnectionSet(self)
        for item in self:
            for key, value in kwargs.iteritems():
                condition = self._get_filter_condition(item, key, value)
                if not condition:
                    filtered_set = filtered_set - set([item])
                    break
        return filtered_set

    def exclude(self, *args, **kwargs):
        if len(args):
            for conn in args:
                if isinstance(conn, AiryHandler):
                    kwargs['session__session_id'] = conn.connection.session.session_id
                else:
                    kwargs['session__session_id'] = conn.session.session_id
        filtered_set = ConnectionSet(self)
        for item in self:
            for key, value in kwargs.iteritems():
                condition = self._get_filter_condition(item, key, value)
                if condition:
                    filtered_set = filtered_set - set([item])
                    break
        return filtered_set

    @property
    def ui(self):
        return UIProxySet(self)

    def __getattr__(self, name):
        def filtered_func(conn_set, name, *args, **kwargs):
            for item in conn_set:
                getattr(item, name)(*args, **kwargs)
            return conn_set
        return curry(filtered_func, self, name)



class UIProxy(object):
    """
    Front-end interaction
    """
    _data = ''

    def __init__(self, connection):
        self.connection = connection

    def execute(self, data):
        """
        Execute JavaScript given in ``data`` on the client side.
        """
        self.connection.emit('execute', data)
        self._data = ''
        return self

    def redirect(self, url):
        """
        Force client to send a GET request to ``url``.

        This may be used to hand the control over to another handler, for example
         after log in you may send the client to a home page handler:

        .. code-block:: python

            # snippet from users/handlers.py:

            class AccountsRegisterHandler(AiryHandler):

                # ...

                def post(self):
                    form = RegistrationForm(self.get_flat_arguments())
                    if form.is_valid():
                        user = form.save(self)
                        # send the client to the homepage handler:
                        self.redirect("/")


        """
        return self.execute('airy.ui.redirect("%s");' % url)

    def insert(self, target, data=None):
        """
        Insert ``data`` into ``target``, where ``target`` is a jQuery selector.

        This is an equivalent to jQuery $.insert() function.
        """
        data = data or self._data
        return self.execute('airy.ui.insert("%s", %s);' % (target, json_encode(data)))


    def after(self, target, data=None):
        """
        Append ``data`` after ``target``, where ``target`` is a jQuery selector.

        This is an equivalent to jQuery $.after() function.
        """
        data = data or self._data
        return self.execute('airy.ui.after("%s", %s);' % (target, json_encode(data)))


    def append(self, target, data=None):
        """
        Append ``data`` to ``target``, where ``target`` is a jQuery selector.

        This is an equivalent to jQuery $.append() function.
        """
        data = data or self._data
        return self.execute('airy.ui.append("%s", %s);' % (target, json_encode(data)))

    def prepend(self, target, data=None):
        """
        Prepend ``data`` to ``target``, where ``target`` is a jQuery selector.

        This is an equivalent to jQuery $.prepend() function.
        """
        data = data or self._data
        return self.execute('airy.ui.prepend("%s", %s);' % (target, json_encode(data)))

    def remove(self, target):
        """
        Remove ``target``, where ``target`` is a jQuery selector.

        This is an equivalent to jQuery $.remove() function.
        """
        return self.execute('airy.ui.remove("%s")' % target)

    def set_title(self, text):
        """
        Set page title to ``text``.
        """
        return self.execute('airy.ui.title("%s")' % text)

    def set_meta_description(self, text):
        """
        Set page meta description to ``text``.
        """
        return self.execute('airy.ui.meta.description("%s")' % text)

    def render_string(self, template_name, **kwargs):
        """
        Render the template specified in ``template_name``.

        **Airy** looks up templates in the folder given in ``settings.template_path`` (default: '.templates/')

        We can use render_string() to obtain the output manually before sending it to the client, for example:

        .. code-block:: python

            class MessagesHandler(AiryHandler):

                def get(self):

                    # the client requests a list of all messages

                    # we will iterate over all messages and send each to the client
                    # adding it to the element matching jQuery selection '#content'
                    # (i.e. with id='content')

                    for message in Message.objects.all():

                        output = self.render_string('messages/message.html', message=message)

                        self.prepend(output, '#content')

        Note: if you want to just insert() the output of render_string() into ``target``, just use render() instead.

        """
        return self.connection.render_string(template_name, **kwargs)

    def render(self, target, template_name, **kwargs):
        """
        Render template into the ``target`` element (jQuery selector).

        This is just a handy shortcut, equivalent to:

        .. code-block:: python

            self.insert(
                target,
                self.render_string(template_name, **kwargs)
            )

        You can use ``self.render()`` to send HTML to the client and insert it directly into ``target``.

        For example, you can have an AiryHandler rendering the home page:

        .. code-block:: python

            class HomeHandler(AiryHandler):

                def get(self):
                    self.render("#content", "accounts/index.html")


        """
        html = self.render_string(template_name, **kwargs)
        self.insert(target, html)
        return self

    def html(self, template_name, **kwargs):
        self._data = self.connection.render_string(template_name, **kwargs)
        return self


class UIProxySet(object):

    def __init__(self, connections):
        self.connections = connections

    def __getattr__(self, name):
        def filtered_func(ui_set, name, *args, **kwargs):
            for item in ui_set.connections:
                getattr(item.ui, name)(*args, **kwargs)
            return ui_set
        return curry(filtered_func, self, name)


class AirySite(object):
    """
    AirySite manages all current Socket.io connections and template loading.
    """
    connections = ConnectionSet()
    application = None
    loader = None

    def resolve_url(self, url, connection, arguments={}):
        handler = None
        args = []
        kwargs = {}

        # unable to check host at the moment, so just loop over all handlers
        for pattern, handlers in self.application.handlers:
            for spec in handlers:
                if issubclass(spec.handler_class, AiryHandler):
                    match = spec.regex.match(url)
                    if match:
                        if spec.regex.groups:
                            # None-safe wrapper around url_unescape to handle
                            # unmatched optional groups correctly
                            def unquote(s):
                                if s is None: return s
                                return escape.url_unescape(s, encoding=None)
                                # Pass matched groups to the handler.  Since
                            # match.groups() includes both named and unnamed groups,
                            # we want to use either groups or groupdict but not both.
                            # Note that args are passed as bytes so the handler can
                            # decide what encoding to use.

                            if spec.regex.groupindex:
                                kwargs = dict(
                                    (k, unquote(v))
                                    for (k, v) in match.groupdict().iteritems())
                            else:
                                args = [unquote(s) for s in match.groups()]
                        handler = spec.handler_class(self, connection, arguments, **spec.kwargs)
                        break

        return handler, args, kwargs

site = AirySite()



class AiryRequestHandler(RequestHandler):
    """
    Old-style handler for plain HTTP requests. Mimics the behaviour
    of Tornado's standard ``RequestHandler`` (from ``tornado.web.RequestHandler``).

    Subclasses are expected to process ordinary HTTP requests.

    An Airy project usually has only one handler which responds to a GET request to any URL
    and is responsible for rendering the base website template, which would establish
    a WebSocket connection.

    All other communication is handled by :py:class:`~airy.core.web.AiryHandler` subclasses.

    For example you may render the default "index" page with an AiryRequestHandler:

    .. code-block:: python

        # snippet from the users app, users/handlers.py:

        class IndexHandler(AiryRequestHandler):

            def get(self):
                self.render("page.html")

    """

    def _flatten_arguments(self, arguments):
        data = {}
        for key, value in arguments.items():
            if len(value) > 1:
                data[key] = value
            else:
                data[key] = value[0]
        return data

    def get_flat_arguments(self):
        """
        Get all arguments as a dictionary where single-value arguments are flat (converted from lists to strings)
        """
        return self._flatten_arguments(self.request.arguments)

    def get_current_user(self):
        """
        Returns a User instance for the current request.

        To fetch current user it loads each backend specified in ``settings.authentication_backends`` and
        calls the ``.get_current_user()`` method of every backend.

        You may specify your own authentication backend in settings and override the default behaviour.

        For more examples refer to the ``users`` app supplied by default with every new project.
        """
        for backend_name in getattr(settings, 'authentication_backends', []):
            backend = __import__(backend_name, fromlist=[backend_name])
            user = backend.get_current_user(self)
            if user:
                return user
        return None

    def get_cookie(self, name, default=None):
        """Gets the value of the cookie with the given ``name``, else ``default``."""
        if self.cookies is not None and name in self.cookies:
            return unquote(self.cookies[name].value)
        return default

    def render_string(self, template_name, **kwargs):
        context_processors = getattr(settings, 'template_context_processors', [])
        template_args = {'reverse_url': self.reverse_url, "_utf8": utf8}
        for processor_path in context_processors:
            path, name = processor_path.rsplit('.', 1)
            processor_module = __import__(path, fromlist=path)
            processor = getattr(processor_module, name)
            template_args.update(processor(self, **kwargs))
        template_args.update(kwargs)
        return super(AiryRequestHandler, self).render_string(template_name, **template_args)

    def is_robot(self, *args, **kwargs):
        robots = [
            'facebook',
            'postrank',
            'voyager',
            'twitterbot',
            'googlebot',
            'slurp',
            'butterfly',
            'pycurl',
            'tweetmemebot',
            'metauri',
            'evrinid',
            'reddit',
            'digg',
        ]
        robots.extend(args)
        for robot in robots:
            if robot.lower() in self.request.headers['User-Agent'].lower():
                return True
        return False



class AiryHandler(object):
    """
    Socket.io base handler, responsible for WebSocket communication.

    All (or most of) your handlers should inherit from AiryHandler.

    It emulates the standard HTTP behaviour by providing callbacks for get() and post() requests,
    for example:

    .. code-block:: python

        # snippet from the users app, users/handlers.py:

        class AccountsLoginHandler(AiryHandler):
            def get(self):
                if self.get_current_user():
                    self.redirect("/")
                else:
                    form = LoginForm()
                    self.render("#content", "accounts/login.html", form=form)

            def post(self):
                form = LoginForm(self.get_flat_arguments())
                if form.is_valid():
                    form.save(self)
                    self.redirect("/")
                else:
                    self.render("#content", "accounts/login.html", form=form)

    This is purely for convenience - in reality all data is sent via WebSockets so technically
    a GET request is no different from a POST request. However to simplify form processing and site
    interaction, we send requests to the appropriate method of a handler.

    """

    def __init__(self, site, connection, arguments={}, **kwargs):
        self.site = site
        self.application = self.site.application
        self.connection = connection
        self.connections = self.site.connections
        self.arguments = {}
        self.files = {}
        for k, values in arguments.iteritems():
            is_file_content = False
            for v in values:
                if isinstance(v, dict) and 'name' in v and 'content' in v:
                    # this looks like a file
                    # so we process it differently
                    try:
                        mimetype, body = v['content'].split(';', 1)
                        encoding, file_content = body.split(',', 1)
                        if encoding == 'base64':
                            file_content = base64.b64decode(file_content)
                        else:
                            raise RuntimeError('Unknown encoding "%s" specified for field "%s"' % (encoding, k))
                        self.files[k] = SimpleUploadedFile(v['name'], file_content, mimetype)
                        is_file_content = True
                    except Exception, e:
                        logging.error("Failed to decode argument '%s'" % k)
                        continue
            if not is_file_content:
                self.arguments[k] = values
        for k,v in kwargs.iteritems():
            setattr(self, k, v)

    #
    # Arguments
    #
    _ARG_DEFAULT = []
    def get_argument(self, name, default=_ARG_DEFAULT, strip=True):
        """Returns the value of the argument with the given name.

        If default is not provided, the argument is considered to be
        required, and we throw an HTTP 400 exception if it is missing.

        If the argument appears in the url more than once, we return the
        last value.

        The returned value is always unicode.
        """
        args = self.get_arguments(name, strip=strip)
        if not args:
            if default is self._ARG_DEFAULT:
                raise HTTPError(400, "Missing argument %s" % name)
            return default
        return args[-1]

    def get_arguments(self, name, strip=True):
        """Returns a list of the arguments with the given name.

        If the argument is not present, returns an empty list.

        The returned values are always unicode.
        """
        values = []
        for v in self.arguments.get(name, []):
            v = self.decode_argument(v, name=name)
            if isinstance(v, unicode):
                # Get rid of any weird control chars (unless decoding gave
                # us bytes, in which case leave it alone)
                v = re.sub(r"[\x00-\x08\x0e-\x1f]", " ", v)
            if strip and (isinstance(v, unicode) or isinstance(v, str)):
                v = v.strip()
            values.append(v)
        return values

    def _flatten_arguments(self, arguments):
        data = {}
        for key, value in arguments.items():
            if isinstance(value, list):
                if len(value) == 0:
                    data[key] = None
                elif len(value) == 1:
                    data[key] = value[0]
                else:
                    data[key] = value
            else:
                data[key] = value
        return data

    def get_flat_arguments(self):
        arguments = {}
        for key in self.arguments:
            arguments[key] = self.get_arguments(key)
        return self._flatten_arguments(arguments)

    def get_files(self):
        return self.files

    def decode_argument(self, value, name=None):
        """Decodes an argument from the request.

        The argument has been percent-decoded and is now a byte string.
        By default, this method decodes the argument as utf-8 and returns
        a unicode string, but this may be overridden in subclasses.

        This method is used as a filter for both get_argument() and for
        values extracted from the url and passed to get()/post()/etc.

        The name of the argument is provided if known, but may be None
        (e.g. for unnamed groups in the url regex).
        """
        return to_unicode(value)


    def __getattr__(self, item):
        return getattr(self.connection, item)



class AiryCoreHandler(SocketConnection):
    "Main Airy handler dealing with WebSocket manipulations"
    state = '/'

    def on_open(self, info):
        self.info = info
        self.site = site
        self.application = site.application
        self.connections = self.site.connections
        self.ui = UIProxy(self)
        logging.info('Socket Connected: %s %s' % (self.info.ip, self.info.arguments.get('t', '')))
        site.connections.add(self)

    @event('set_state')
    def set_state(self, state):
        (scheme, host, path, arguments) = self.parse_url(state)
        self.state = path

    @event('get')
    @report_on_fail
    def get(self, url, *args, **kwargs):
        "Main entry point for WebSocket requests"
        (scheme, host, path, arguments) = self.parse_url(url)
        handler, hargs, hkwargs = site.resolve_url(path, self, arguments=arguments)
        hargs.extend(args)
        hkwargs.update(kwargs)
        if handler:
            logging.info('GET %s from %s %s => %s' % (path, self.info.ip,
                                                      self.info.arguments.get('t', ''),
                                                      handler.__class__.__name__))
            try:
                return handler.get(*hargs, **hkwargs)
            except Http404:
                self.process_404(*hargs, **hkwargs)
        else:
            logging.error('GET %s from %s %s failed: no handler found' % \
                          (path, self.info.ip, self.info.arguments.get('t', '')))
            self.process_404(*hargs, **hkwargs)

    @event('post')
    @report_on_fail
    def post(self, url, *args, **kwargs):
        "Main entry point for WebSocket requests"
        (scheme, host, path, arguments) = self.parse_url(url)
        args = list(args)
        try:
            data = args.pop(0)
            for k, v in dict(data).items():
                if not isinstance(v, list):
                    data[k] = [v]
        except:
            data = {}
        arguments.update(data)
        handler, hargs, hkwargs = site.resolve_url(path, self, arguments=arguments)
        hargs.extend(args)
        hkwargs.update(kwargs)
        if handler:
            logging.info('POST %s from %s %s => %s' % (
                path, self.info.ip, self.info.arguments.get('t', ''), handler.__class__.__name__)
            )
            try:
                return handler.post(*hargs, **hkwargs)
            except Http404:
                self.process_404(*hargs, **hkwargs)
        else:
            logging.error('POST %s from %s %s failed: no handler found' % \
                          (path, self.info.ip, self.info.arguments.get('t', '')))
            self.process_404(*hargs, **hkwargs)

    def on_close(self):
        logging.info('Socket Disconnected: %s %s' % (self.info.ip, self.info.arguments.get('t', '')))
        self.site.connections.remove(self)

    #
    # Cookies
    #
    @property
    def cookies(self):
        return self.info.cookies

    def get_cookie(self, name, default=None):
        """Gets the value of the cookie with the given name, else default."""
        if self.info.cookies is not None and name in self.info.cookies:
            return unquote(self.info.cookies[name].value)
        return default

    def set_cookie(self, name, value, domain=None, expires=None, path="/",
                   expires_days=None, **kwargs):
        """Sets the given cookie name/value with the given options.

        Additional keyword arguments are set on the Cookie.Morsel
        directly.
        See http://docs.python.org/library/cookie.html#morsel-objects
        for available attributes.
        """
        # The cookie library only accepts type str, in both python 2 and 3
        name = escape.native_str(name)
        value = escape.native_str(value)
        if re.search(r"[\x00-\x20]", name + value):
            # Don't let us accidentally inject bad stuff
            raise ValueError("Invalid cookie %r: %r" % (name, value))

        options = {}
        if domain:
            options["domain"] = domain
        if expires_days is not None and not expires:
            expires = datetime.datetime.utcnow() + datetime.timedelta(
                days=expires_days)
        if expires:
            options["expires"] = calendar.timegm(expires.utctimetuple())
        if path:
            options["path"] = path
        for k, v in kwargs.iteritems():
            if k == 'max_age': k = 'max-age'
            options[k] = v

        self.info.cookies[name] = value
        self.ui.execute('airy.set_cookie("%s", "%s", %s);' % (name, value, json_encode(options)))

    def clear_cookie(self, name, path="/", domain=None):
        """Deletes the cookie with the given name."""
        try:
            del self.cookies[name]
        except KeyError:
            pass
        self.ui.execute('airy.set_cookie("%s", null);' % name)

    def clear_all_cookies(self):
        """Deletes all the cookies the user sent with this request."""
        for name in self.info.cookies.iterkeys():
            self.clear_cookie(name)

    def set_secure_cookie(self, name, value, expires_days=30, **kwargs):
        """Signs and timestamps a cookie so it cannot be forged.

        You must specify the ``cookie_secret`` setting in your Application
        to use this method. It should be a long, random sequence of bytes
        to be used as the HMAC secret for the signature.

        To read a cookie set with this method, use `get_secure_cookie()`.

        Note that the ``expires_days`` parameter sets the lifetime of the
        cookie in the browser, but is independent of the ``max_age_days``
        parameter to `get_secure_cookie`.
        """
        self.set_cookie(name, self.create_signed_value(name, value),
            expires_days=expires_days, **kwargs)

    def create_signed_value(self, name, value):
        """Signs and timestamps a string so it cannot be forged.

        Normally used via set_secure_cookie, but provided as a separate
        method for non-cookie uses.  To decode a value not stored
        as a cookie use the optional value argument to get_secure_cookie.
        """
        self.require_setting("cookie_secret", "secure cookies")
        return create_signed_value(self.application.settings["cookie_secret"],
            name, value)

    def get_secure_cookie(self, name, value=None, max_age_days=31):
        """Returns the given signed cookie if it validates, or None."""
        self.require_setting("cookie_secret", "secure cookies")
        if value is None: value = self.get_cookie(name)
        return decode_signed_value(self.application.settings["cookie_secret"],
            name, value, max_age_days=max_age_days)

    #
    # Arguments
    #
    _ARG_DEFAULT = []
    def get_argument(self, name, default=_ARG_DEFAULT, strip=True):
        """Returns the value of the argument with the given name.

        If default is not provided, the argument is considered to be
        required, and we throw an HTTP 400 exception if it is missing.

        If the argument appears in the url more than once, we return the
        last value.

        The returned value is always unicode.
        """
        args = self.get_arguments(name, strip=strip)
        if not args:
            if default is self._ARG_DEFAULT:
                raise HTTPError(400, "Missing argument %s" % name)
            return default
        return args[-1]

    def get_arguments(self, name, strip=True):
        """Returns a list of the arguments with the given name.

        If the argument is not present, returns an empty list.

        The returned values are always unicode.
        """
        values = []
        for v in self.info.arguments.get(name, []):
            v = self.decode_argument(v, name=name)
            if isinstance(v, unicode):
                # Get rid of any weird control chars (unless decoding gave
                # us bytes, in which case leave it alone)
                v = re.sub(r"[\x00-\x08\x0e-\x1f]", " ", v)
            if strip and (isinstance(v, unicode) or isinstance(v, str)):
                v = v.strip()
            values.append(v)
        return values

    def _flatten_arguments(self, arguments):
        data = {}
        for key, value in arguments.items():
            if isinstance(value, list):
                if len(value) == 0:
                    data[key] = None
                elif len(value) == 1:
                    data[key] = value[0]
                else:
                    data[key] = value
            else:
                data[key] = value
        return data

    def get_flat_arguments(self):
        arguments = {}
        for key in self.info.arguments:
            arguments[key] = self.get_arguments(key)
        return self._flatten_arguments(arguments)

    def get_files(self):
        return self.files

    def decode_argument(self, value, name=None):
        """Decodes an argument from the request.

        The argument has been percent-decoded and is now a byte string.
        By default, this method decodes the argument as utf-8 and returns
        a unicode string, but this may be overridden in subclasses.

        This method is used as a filter for both get_argument() and for
        values extracted from the url and passed to get()/post()/etc.

        The name of the argument is provided if known, but may be None
        (e.g. for unnamed groups in the url regex).
        """
        return to_unicode(value)


    #
    # Authentication
    #
    @property
    def current_user(self):
        """The authenticated user for this request.

        Determined by either get_current_user, which you can override to
        set the user based on, e.g., a cookie. If that method is not
        overridden, this method always returns None.

        We lazy-load the current user the first time this method is called
        and cache the result after that.
        """
        if not hasattr(self, "_current_user"):
            self._current_user = self.get_current_user()
        return self._current_user

    def get_current_user(self):
        for backend_name in getattr(settings, 'authentication_backends', []):
            backend = __import__(backend_name, fromlist=[backend_name])
            user = backend.get_current_user(self)
            if user:
                return user
        return None

    #
    # URL handling
    #
    def require_setting(self, name, feature="this feature"):
        """Raises an exception if the given app setting is not defined."""
        if not self.site.application.settings.get(name):
            raise Exception("You must define the '%s' setting in your "
                            "application to use %s" % (name, feature))

    def get_login_url(self):
        """Override to customize the login URL based on the request. By default, we use the 'login_url' application setting."""
        self.require_setting("login_url", "@tornado.web.authenticated")
        return self.site.application.settings["login_url"]

    def process_404(self, *args, **kwargs):
        try:
            handler_path = settings.page_not_found_handler
            path, name = handler_path.rsplit('.', 1)
            handler_module = __import__(path, fromlist=path)
            handler_class = getattr(handler_module, name)
            handler_class(site, self).get()
        except AttributeError:
            logging.error('Page with url %s doesn\'t exist' % (kwargs.get('url', ''), ))

    def parse_url(self, url):
        "Returns a tuple in the form (scheme, host, path, arguments)"
        parsed = urlparse(url)
        arguments = parse_qs(parsed.query)
        return parsed.scheme, parsed.netloc, parsed.path, arguments

    def reverse_url(self, name, *args):
        """Alias for `Application.reverse_url`."""
        return self.application.reverse_url(name, *args)

    #
    # Airy client interaction
    #
    def render_string(self, template_name, **kwargs):
        "Render the given template"
        context_processors = getattr(settings, 'template_context_processors', [])
        template_args = {'reverse_url': self.reverse_url}
        for processor_path in context_processors:
            path, name = processor_path.rsplit('.', 1)
            processor_module = __import__(path, fromlist=path)
            processor = getattr(processor_module, name)
            template_args.update(processor(self, **kwargs))

        template_args.update(kwargs)
        html = self.site.loader.load(template_name).generate(**template_args)
        return html

    def __getattr__(self, item):
        # Front-end proxy
        return getattr(self.ui, item)




class FormProcessor(AiryRequestHandler):
    """
    Temporary form processor for old browsers with no FileAPI.

    This seems to be the only way to support file uploads (facepalm)
    """
    def check_xsrf_cookie(self):
        # don't check XSRF
        pass

    def post(self, *args, **kwargs):
        args = self.get_flat_arguments()
        args['files'] = {}
        for file in self.request.files:
            if len(self.request.files[file]) > 1:
                for content in self.request.files[file]:
                    args['files'][file] = {
                        'content': '%s;%s,%s' % (content['content_type'], 'base64', base64.b64encode(content['body'])),
                        'name': smart_unicode(content['filename'])
                    }
            else:
                content = self.request.files[file][0]
                args['files'][file] = {
                    'content': '%s;%s,%s' % (content['content_type'], 'base64', base64.b64encode(content['body'])),
                    'name': smart_unicode(content['filename'])
                }
        self.write(json_encode(args))
        self.finish()


def utf8(value):
    """Converts a string argument to a byte string.

    If the argument is already a byte string or None, it is returned unchanged.
    Otherwise it must be a unicode string and is encoded as utf8.
    """
    if isinstance(value, _UTF8_TYPES):
        return value
    assert isinstance(value, unicode)
    return smart_unicode(value, encoding="utf-8", errors="ignore")

_UTF8_TYPES = (bytes, type(None))


