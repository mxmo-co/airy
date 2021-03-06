"""
Basic decorators
"""

def bot_friendly(func):

    def wrapped(obj, *args, **kwargs):
        from lxml.html import document_fromstring, tostring, fromstring
        from lxml.etree import ParserError
        from airy.core.web import site

        def get_current_user():
            return None

        def render(target, template_name, **kwargs):
            try:
                document = document_fromstring(obj.HTML)
                fragment = fromstring(handler.render_string(template_name, **kwargs))
                document.get_element_by_id(target[1:]).insert(0, fragment)
                obj.HTML = tostring(document)
            except ParserError:
                pass

        def append(target, data):
            document = document_fromstring(obj.HTML)
            to = document.get_element_by_id(target[1:])
            to.append(fromstring(data))
            obj.HTML = tostring(document)

        def prepend(target, data):
            document = document_fromstring(obj.HTML)
            to = document.get_element_by_id(target[1:])
            to.insert(0, fromstring(data))
            obj.HTML = tostring(document)

        def redirect(url):
            super(obj.__class__, obj).redirect(url)

        def remove(target):
            document = document_fromstring(obj.HTML)
            fragment = document.get_element_by_id(target[1:])
            document.remove(fragment)
            obj.HTML = tostring(document)

        def set_title(text):
            document = document_fromstring(obj.HTML)
            document.findall('.//title')[0].text = text
            obj.HTML = tostring(document)

        def set_meta_description(text):
            document = document_fromstring(obj.HTML)
            try:
                document.findall('.//head/meta[@name="description"]')[0].attrib['content'] = text
            except IndexError:
                pass
            obj.HTML = tostring(document)

        if obj.is_robot():
            obj.HTML = obj.render_string("page.html")
            uri = obj.request.uri
            arguments = obj.request.arguments
            handler, hargs, hkwargs = site.resolve_url(uri, None, arguments)
            handler.get_current_user = get_current_user
            handler.append = append
            handler.redirect = redirect
            handler.remove = remove
            handler.render = render
            handler.prepend = prepend
            handler.set_title = set_title
            handler.set_meta_description = set_meta_description
            handler.get(*hargs, **hkwargs)

            HTML = obj.HTML
            return obj.finish(HTML)
        return func(obj, *args, **kwargs)

    wrapped.__doc__ = func.__doc__
    wrapped.__name__ = func.__name__

    return wrapped
