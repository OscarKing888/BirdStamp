from birdstamp.template_loader import normalize_template_dict


def test_normalize_template_dict_clamps_values() -> None:
    template = normalize_template_dict(
        {
            "name": "custom",
            "banner_height": 20,
            "left_ratio": 2.0,
            "padding": {"x": -10, "y": 4},
            "fonts": {"title": 1, "body": 2, "small": 3},
            "colors": {"background": "#000000"},
            "divider": False,
        }
    )
    assert template.name == "custom"
    assert template.banner_height == 80
    assert template.left_ratio == 0.8
    assert template.padding_x == 8
    assert template.padding_y == 8
    assert template.fonts["title"] == 10
    assert template.fonts["body"] == 10
    assert template.fonts["small"] == 8
    assert template.colors["background"] == "#000000"
    assert template.divider is False

