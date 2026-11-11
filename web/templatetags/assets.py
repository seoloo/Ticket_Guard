"""{% asset 'app.css' %} -> /static/app.css?v=<file mtime>

The URL changes whenever the file is saved, so every browser (Chrome,
VS Code Simple Browser) fetches the new CSS/JS instead of a cached copy.
"""
import os
from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def asset(path):
    url = static(path)
    found = finders.find(path)
    if isinstance(found, str):
        try:
            return f'{url}?v={int(os.path.getmtime(found))}'
        except OSError:
            pass
    return url
