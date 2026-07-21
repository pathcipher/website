from django import template

from wagtail.models import Site

register = template.Library()


@register.simple_tag(takes_context=True)
def get_site_root(context):
    """Return the root page of the current site (or None)."""
    request = context.get("request")
    site = Site.find_for_request(request) if request else Site.objects.filter(
        is_default_site=True
    ).first()
    return site.root_page if site else None


@register.inclusion_tag("includes/main_menu.html", takes_context=True)
def main_menu(context):
    """Top-level pages flagged 'show in menus', for the header nav."""
    root = get_site_root(context)
    menu_items = []
    if root:
        menu_items = (
            root.get_children().live().in_menu().specific()
        )
    return {
        "menu_items": menu_items,
        "root": root,
        "request": context.get("request"),
    }
