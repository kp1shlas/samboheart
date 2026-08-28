from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Доступ к словарю по ключу в шаблоне"""
    if dictionary is None:
        return None
    return dictionary.get(key)