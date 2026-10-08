"""Each Sumner commissioner gets their OWN photo.

The county page renders a post's image before its title widget, so the photo
belongs to the chunk that precedes the title. Reading the title's own chunk gave
every commissioner the next one's photo.
"""
from beholden_etl.sources.tn_local import parse_sumner


def _post(name, slug, district, photo):
    img = f'<img src="https://x.test/{photo}.jpg">' if photo else ""
    return (f'<div class="elementor-widget-image">{img}</div>'
            f'<div class="elementor-widget-theme-post-title"><h3><a href="https://x.test/{slug}/">{name}</a></h3></div>'
            f'<div class="elementor-widget-theme-post-excerpt"><div class="elementor-widget-container">{district}st District</div></div>'
            f'<a href="mailto:{slug}@x.test">mail</a>')


def test_photo_follows_the_person():
    page = '<img src="https://x.test/logo.png">' + _post("Ann", "ann", 1, "ann") + \
        _post("Bob", "bob", 2, "bob") + _post("Cy", "cy", 3, "cy") + '<img src="https://x.test/logo.png">'
    rows = {r["full_name"]: r for r in parse_sumner(page)}
    assert {n: r["photo_url"] for n, r in rows.items()} == {
        "Ann": "https://x.test/ann.jpg", "Bob": "https://x.test/bob.jpg", "Cy": "https://x.test/cy.jpg"}
    assert rows["Bob"]["email"] == "bob@x.test"


def test_missing_photo_is_none_not_a_neighbours():
    page = '<img src="https://x.test/logo.png">' + _post("Ann", "ann", 1, "ann") + \
        _post("Bob", "bob", 2, None) + _post("Cy", "cy", 3, "cy")
    rows = {r["full_name"]: r["photo_url"] for r in parse_sumner(page)}
    assert rows["Bob"] is None and rows["Cy"] == "https://x.test/cy.jpg"
