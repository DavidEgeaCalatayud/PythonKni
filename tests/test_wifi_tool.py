from tools.wifi_tool import _parse_profiles


def test_parse_profiles_accepts_english_and_spanish_labels():
    output = """
    All User Profile     : Office
    Perfil de todos los usuarios : Casa
    """

    assert _parse_profiles(output) == ["Office", "Casa"]
