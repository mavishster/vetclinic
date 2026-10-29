"""Безопасный HTML для текстов, которые пишут пользователи (медкарта, шаблоны).

Текст показывается в браузере как HTML, поэтому перед сохранением из него убирается
всё опасное: скрипты, обработчики событий, посторонние атрибуты. Остаётся оформление
текста, списки, таблицы, картинки и отметки позиций прайса.
"""

import nh3

TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "strike", "sub", "sup",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "blockquote", "hr", "div", "span", "font",
    "table", "thead", "tbody", "tr", "th", "td", "a", "img", "pre", "code",
}  # fmt: skip

ATTRIBUTES = {
    "span": {"class", "data-item-unit", "contenteditable", "style"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "style"},
    "th": {"colspan", "rowspan", "style"},
    "font": {"color", "size"},
    "div": {"style"},
    "p": {"style"},
}

CSS = {"color", "background-color", "text-align", "font-weight", "font-style", "text-decoration"}


def clean(html: str) -> str:
    """Убрать из HTML всё, кроме безопасного оформления."""
    return nh3.clean(
        html or "",
        tags=TAGS,
        attributes=ATTRIBUTES,
        filter_style_properties=CSS,
        url_schemes={"http", "https", "data"},
        link_rel="noopener noreferrer",
    )
