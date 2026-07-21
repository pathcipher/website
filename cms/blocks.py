"""
Reusable StreamField blocks for building flashy public pages without code.

Editors compose pages from these in the Wagtail admin. Keep the block set
small and opinionated so the site stays visually consistent.
"""
from wagtail import blocks
from wagtail.images.blocks import ImageChooserBlock


class HeadingBlock(blocks.StructBlock):
    text = blocks.CharBlock(required=True)
    size = blocks.ChoiceBlock(
        choices=[("h2", "Large"), ("h3", "Medium"), ("h4", "Small")],
        default="h2",
    )

    class Meta:
        icon = "title"
        template = "cms/blocks/heading_block.html"
        label = "Heading"


class CalloutBlock(blocks.StructBlock):
    """A punchy highlighted statement / stat."""

    label = blocks.CharBlock(required=False, help_text="Small kicker above the number")
    value = blocks.CharBlock(required=True, help_text="e.g. '2,000+' or '4.9★'")
    caption = blocks.CharBlock(required=False)

    class Meta:
        icon = "pick"
        template = "cms/blocks/callout_block.html"
        label = "Stat / callout"


class FeatureCardBlock(blocks.StructBlock):
    icon_emoji = blocks.CharBlock(required=False, help_text="An emoji, e.g. 🧩")
    title = blocks.CharBlock(required=True)
    body = blocks.TextBlock(required=False)
    image = ImageChooserBlock(required=False)

    class Meta:
        icon = "form"
        template = "cms/blocks/feature_card_block.html"
        label = "Feature card"


class StatRowBlock(blocks.StructBlock):
    """A responsive row of stat/callout cards."""

    stats = blocks.ListBlock(CalloutBlock())

    class Meta:
        icon = "list-ul"
        template = "cms/blocks/stat_row_block.html"
        label = "Stat row"


class FeatureGridBlock(blocks.StructBlock):
    """A responsive grid of feature cards."""

    heading = blocks.CharBlock(required=False)
    cards = blocks.ListBlock(FeatureCardBlock())

    class Meta:
        icon = "grip"
        template = "cms/blocks/feature_grid_block.html"
        label = "Feature grid"


class CTABlock(blocks.StructBlock):
    heading = blocks.CharBlock(required=True)
    text = blocks.TextBlock(required=False)
    button_label = blocks.CharBlock(required=True, default="Get in touch")
    button_url = blocks.URLBlock(required=False)
    button_page = blocks.PageChooserBlock(required=False)

    class Meta:
        icon = "plus-inverse"
        template = "cms/blocks/cta_block.html"
        label = "Call to action"


class BodyStreamBlock(blocks.StreamBlock):
    """The main content stream used across public pages."""

    heading = HeadingBlock()
    paragraph = blocks.RichTextBlock(
        features=["bold", "italic", "link", "ol", "ul", "hr"],
        icon="pilcrow",
    )
    image = ImageChooserBlock(icon="image")
    quote = blocks.BlockQuoteBlock(icon="openquote")
    stat_row = StatRowBlock()
    feature_grid = FeatureGridBlock()
    cta = CTABlock()
    embed = blocks.RawHTMLBlock(
        required=False,
        help_text="Raw HTML for embeds/animations. Admins only.",
        icon="code",
    )

    class Meta:
        block_counts = {}
