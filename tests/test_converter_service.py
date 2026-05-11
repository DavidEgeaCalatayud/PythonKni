from tools.converter_tool import validate_extension


def test_validate_extension_accepts_case_insensitive_extensions():
    assert validate_extension("photo.JPG", {".jpg", ".png"})


def test_validate_extension_rejects_unknown_extensions():
    assert not validate_extension("document.exe", {".jpg", ".png"})
