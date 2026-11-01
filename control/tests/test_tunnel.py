from control.tunnel import configuration, public_link
from unittest.mock import Mock
import time


def test_tunnel_targets_only_platform_and_disables_inspector():
    config = configuration("team-hcc")
    assert config["inspect"]["enabled"] is False
    assert config["tunnels"] == [{"name": "hcc-platform", "type": "http", "local_port": 8000,
                                 "local_addr": "127.0.0.1", "subdomain": "team-hcc"}]
    assert config["reconnect"]["max_attempts"] == 5


def test_public_link_rejects_other_hosts_and_console_secret_values():
    assert public_link('HTTP: https://team-hcc.fxtun.ru') == 'https://team-hcc.fxtun.ru'
    assert public_link('https://evil.example password=secret') is None
    assert public_link('https://team.fxtun.ru.evil.example') is None
    assert public_link('https://team.fxtun.ru/path?token=secret') is None


def test_exited_child_is_released_for_retry(tmp_path):
    from control.tunnel import Tunnel
    tunnel = Tunnel(tmp_path)
    process = Mock()
    process.poll.return_value = 1
    tunnel.process = process
    tunnel.check()
    assert tunnel.process is None


def test_connection_without_address_has_deadline(tmp_path):
    from control.tunnel import Tunnel
    tunnel = Tunnel(tmp_path)
    process = Mock()
    process.poll.return_value = None
    tunnel.process = process
    tunnel.started = time.time() - 61
    tunnel.check()
    assert tunnel.process is None
    process.terminate.assert_called_once()
    assert '60' in tunnel.error
