from django.db import models

from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.models import Page

from .blocks import BodyStreamBlock


class HomePage(Page):
    """The flashy landing page. One per site, typically the site root."""

    hero_kicker = models.CharField(
        max_length=120,
        blank=True,
        help_text="Small line above the hero heading.",
    )
    hero_heading = models.CharField(
        max_length=255,
        blank=True,
        help_text="Big bold headline.",
    )
    hero_subheading = models.TextField(
        blank=True,
        help_text="Supporting sentence under the hero heading.",
    )
    hero_cta_label = models.CharField(max_length=60, blank=True)
    hero_cta_page = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Where the hero button links to.",
    )
    hero_image = models.ForeignKey(
        "wagtailimages.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    body = StreamField(
        BodyStreamBlock(),
        blank=True,
        help_text="Build the rest of the page from content blocks.",
    )

    content_panels = Page.content_panels + [
        FieldPanel("hero_kicker"),
        FieldPanel("hero_heading"),
        FieldPanel("hero_subheading"),
        FieldPanel("hero_cta_label"),
        FieldPanel("hero_cta_page"),
        FieldPanel("hero_image"),
        FieldPanel("body"),
    ]

    # Only one home page at the top; children are standard pages.
    subpage_types = ["cms.StandardPage"]

    class Meta:
        verbose_name = "Home page"


class StandardPage(Page):
    """A generic content page (About, Experiences, Pricing, Contact, etc.)."""

    intro = RichTextField(
        blank=True,
        features=["bold", "italic", "link"],
        help_text="Short intro shown under the page title.",
    )
    body = StreamField(BodyStreamBlock(), blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("intro"),
        FieldPanel("body"),
    ]

    subpage_types = ["cms.StandardPage"]
