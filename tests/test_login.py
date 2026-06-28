import unittest
from unittest.mock import MagicMock, patch
import sys
import pytest
from pathlib import Path

pytest.importorskip("msgpack")
pytest.importorskip("frida")

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "uma_api"))

from uma_api.client import UmaClient

class TestUmaLogin(unittest.TestCase):

    def setUp(self):
        # Setup configuration with Steam credentials but viewer_id = 0
        self.cfg = {
            "viewer_id": 0,
            "udid": "12345678-1234-1234-1234-123456789012",
            "auth_key": "YOUR_AUTH_KEY_HERE",
            "steam_id": "76561198090612460",
            "steam_session_ticket": "MOCK_STEAM_TICKET_HEX",
            "app_ver": "3.10.5",
            "res_ver": "12345678",
            "device_id": "mock_device_id",
            "device_name": "mock_device",
            "graphics_device_name": "mock_gpu",
            "ip_address": "127.0.0.1",
            "platform_os_version": "Windows 11",
        }

    def test_has_captured_auth_with_steam(self):
        client = UmaClient(self.cfg, trace_enabled=False)
        # Should return True even if viewer_id is 0 because we have steam credentials
        self.assertTrue(client.has_captured_auth())

    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_login_bypasses_signup_and_aligns(self, mock_unpack_func, mock_session_cls):
        # Mock session object returned by requests.Session()
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "dummy_response_text"
        mock_session.post = MagicMock(return_value=mock_response)
        
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()
        
        # Define mock responses sequentially:
        # 1. tool/start_session
        # 2. load/index
        # 3. read_info/index
        unpack_responses = [
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907,
                    "sid": "MOCK_NEW_SID_HEX"
                },
                "data": {}
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907
                },
                "data": {
                    "tp_info": {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0},
                    "coin_info": {"fcoin": 100, "coin": 0}
                }
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907
                },
                "data": {}
            }
        ]
        
        call_counter = [0]
        def mock_unpack(text, udid):
            idx = call_counter[0]
            call_counter[0] += 1
            if idx < len(unpack_responses):
                return unpack_responses[idx]
            return {}

        mock_unpack_func.side_effect = mock_unpack
        
        # Call login
        res = client.login()
        
        # Verify signup was NOT called
        client.signup.assert_not_called()
        
        # Verify client's viewer_id aligned to the correct Steam ID
        self.assertEqual(client.viewer_id, 5390138731907)
        
        # Verify that start_session and load/index post requests were made
        self.assertEqual(mock_session.post.call_count, 3)
        print("Integration login test passed successfully!")

    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    @patch('uma_api.client.get_ticket')
    def test_login_retry_reuses_ticket(self, mock_get_ticket, mock_unpack_func, mock_session_cls):
        # Mock get_ticket (should not be called)
        mock_get_ticket.return_value = ("76561198090612460", "NEW_MOCK_TICKET_HEX")

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "dummy_response_text"
        mock_session.post = MagicMock(return_value=mock_response)

        # Configure client with steam credentials
        self.cfg["steam_username"] = "test_user"
        self.cfg["steam_password"] = "test_pass"
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()

        # Mock responses:
        # First attempt tool/start_session fails with 202
        # Second attempt tool/start_session succeeds with result_code = 1
        # Second attempt load/index succeeds with result_code = 1
        # Second attempt read_info/index succeeds with result_code = 1
        unpack_responses = [
            {
                "data_headers": {
                    "result_code": 202,
                    "viewer_id": 0,
                    "sid": ""
                },
                "data": {}
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907,
                    "sid": "MOCK_NEW_SID_HEX"
                },
                "data": {}
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907
                },
                "data": {
                    "tp_info": {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0},
                    "coin_info": {"fcoin": 100, "coin": 0}
                }
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907
                },
                "data": {}
            }
        ]

        call_counter = [0]
        def mock_unpack(text, udid):
            idx = call_counter[0]
            call_counter[0] += 1
            if idx < len(unpack_responses):
                return unpack_responses[idx]
            return {}

        mock_unpack_func.side_effect = mock_unpack

        # Call login
        res = client.login(max_retries=1)

        # Verify get_ticket was NOT called (ticket is reused)
        mock_get_ticket.assert_not_called()
        self.assertEqual(client.steam_ticket, "MOCK_STEAM_TICKET_HEX")
        self.assertEqual(client.viewer_id, 5390138731907)
        print("Login retry ticket reuse test passed!")

    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    @patch('uma_api.client.get_ticket')
    def test_refresh_index_state_retry_reuses_ticket(self, mock_get_ticket, mock_unpack_func, mock_session_cls):
        # Import main
        import main
        
        # Mock get_ticket (should not be called)
        mock_get_ticket.return_value = ("76561198090612460", "NEW_MOCK_TICKET_HEX")

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "dummy_response_text"
        mock_session.post = MagicMock(return_value=mock_response)

        # Configure client with steam credentials
        self.cfg["steam_username"] = "test_user"
        self.cfg["steam_password"] = "test_pass"
        client = UmaClient(self.cfg, trace_enabled=False)

        # Mock responses:
        # First tool/start_session fails with 202
        # Second tool/start_session succeeds with result_code = 1
        # Second load/index succeeds with result_code = 1
        unpack_responses = [
            {
                "data_headers": {
                    "result_code": 202,
                    "viewer_id": 0,
                    "sid": ""
                },
                "data": {}
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907,
                    "sid": "MOCK_NEW_SID_HEX"
                },
                "data": {}
            },
            {
                "data_headers": {
                    "result_code": 1,
                    "viewer_id": 5390138731907
                },
                "data": {}
            }
        ]

        call_counter = [0]
        def mock_unpack(text, udid):
            idx = call_counter[0]
            call_counter[0] += 1
            if idx < len(unpack_responses):
                return unpack_responses[idx]
            return {}

        mock_unpack_func.side_effect = mock_unpack

        # Call refresh_index_state
        res = main.refresh_index_state(client, max_retries=1)

        # Verify get_ticket was NOT called (ticket is reused)
        mock_get_ticket.assert_not_called()
        self.assertEqual(client.steam_ticket, "MOCK_STEAM_TICKET_HEX")
        print("Refresh index state ticket reuse test passed!")

    def test_client_proxy_applied(self):
        self.cfg["proxy_url"] = "socks5://127.0.0.1:1080"
        client = UmaClient(self.cfg, trace_enabled=False)
        self.assertEqual(client.session.proxies.get("http"), "socks5://127.0.0.1:1080")
        self.assertEqual(client.session.proxies.get("https"), "socks5://127.0.0.1:1080")
        print("Client proxy applied test passed!")

    @patch('uma_api.client.subprocess.run')
    def test_get_ticket_passes_proxy(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"steam_id": "76561198090612460", "session_ticket": "MOCK_TICKET"}\n'
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        from uma_api.client import get_ticket
        get_ticket("user", "pass", "12345", "socks5://127.0.0.1:1080")
        
        # Verify command args
        args = mock_run.call_args[0][0]
        self.assertIn("--proxy", args)
        self.assertIn("socks5://127.0.0.1:1080", args)
        print("Get ticket passes proxy test passed!")

if __name__ == '__main__':
    unittest.main()
