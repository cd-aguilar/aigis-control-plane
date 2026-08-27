from config_loader import load_settings


def test_max_retries_matches_ops_runbook():
    settings = load_settings()
    assert settings['max_retries'] == 3
