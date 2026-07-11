import unittest
from unittest.mock import MagicMock, patch
import sys
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

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
        # read_info/index is no longer called by the client.
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
        self.assertEqual(mock_session.post.call_count, 2)
        print("Integration login test passed successfully!")

    def test_read_info_is_noop(self):
        client = UmaClient(self.cfg, trace_enabled=False)
        client.call = MagicMock(side_effect=AssertionError("read_info/index must not be called"))

        self.assertIsNone(client.read_info())
        client.call.assert_not_called()

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.unpack')
    @patch('uma_api.client.requests.Session')
    def test_res_ver_update_resets_session_before_retrying_load_index(self, mock_session_cls, mock_unpack, _mock_pack):
        first_session = MagicMock()
        second_session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.text = "packed"
        first_session.post.return_value = response
        second_session.post.return_value = response
        mock_session_cls.side_effect = [first_session, second_session]
        mock_unpack.side_effect = [
            {"data_headers": {"result_code": 214, "resource_version": "10006820"}, "data": {}},
            {"data_headers": {"result_code": 1}, "data": {}},
            {"data_headers": {"result_code": 1}, "data": {"tp_info": {"current_tp": 30}}},
        ]
        client = UmaClient(self.cfg | {"res_ver": "10006810"}, trace_enabled=False)

        with TemporaryDirectory() as tmp_dir, patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
            result = client.call("load/index", {"adid": ""})

        assert result["data"]["tp_info"]["current_tp"] == 30
        self.assertTrue(first_session.close.called)
        posted_urls = [call.args[0] for call in second_session.post.call_args_list]
        self.assertTrue(any(url.endswith("tool/start_session") for url in posted_urls))
        self.assertTrue(any(url.endswith("load/index") for url in posted_urls))
        self.assertEqual(client.res_ver, "10006820")

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

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_call_relogs_in_after_start_session_501(self, mock_unpack_func, mock_session_cls, _mock_pack):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({"viewer_id": 5390138731907, "auth_key": "66616b655f617574685f6b6579"})
        client = UmaClient(self.cfg, trace_enabled=False)
        client._refresh_ticket_and_login = MagicMock()
        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 1, "viewer_id": 5390138731907}, "data": {}},
        ]

        res = client.call('tool/start_session', {'attestation_type': 0, 'device_token': None})

        self.assertEqual(res["data_headers"]["result_code"], 1)
        client._refresh_ticket_and_login.assert_called_once_with()
        self.assertEqual(mock_session.post.call_count, 2)

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    @patch('uma_api.client.get_ticket')
    def test_login_recovers_start_session_501_via_cached_transition(self, mock_get_ticket, mock_unpack_func, mock_session_cls, _mock_pack):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({
            "viewer_id": 5390138731907,
            "auth_key": "66616b655f617574685f6b6579",
            "steam_username": "test_user",
            "steam_password_seed": "test_pass",
        })
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()

        # authed start 501 → anon start 501 → chain → get → anon start → load
        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 1}, "data": {"viewer_id": 5390138731907, "auth_key": "bmV3X2F1dGhfa2V5"}},
            {"data_headers": {"result_code": 1}, "data": {"viewer_id": 5390138731907, "auth_key": "bmV3X2F1dGhfa2V5"}},
            {"data_headers": {"result_code": 1, "viewer_id": 5390138731907, "sid": "MOCK_NEW_SID_HEX"}, "data": {}},
            {"data_headers": {"result_code": 1, "viewer_id": 5390138731907}, "data": {"tp_info": {"current_tp": 100}}},
        ]

        with TemporaryDirectory() as tmp_dir:
            cache = Path(tmp_dir) / "auth_cache.json"
            cache.write_text('{"uma_password_hash":"pw_hash"}', encoding="utf-8")
            with patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
                res = client.login(max_retries=1)

        posted_urls = [call.args[0] for call in mock_session.post.call_args_list]
        self.assertTrue(any(url.endswith("account/chain_by_transition_code") for url in posted_urls))
        self.assertTrue(any(url.endswith("account/get_by_transition_code") for url in posted_urls))
        self.assertTrue(posted_urls[-2].endswith("tool/start_session"))
        self.assertTrue(posted_urls[-1].endswith("load/index"))
        self.assertEqual(res["data"]["tp_info"]["current_tp"], 100)
        mock_get_ticket.assert_not_called()
        client.signup.assert_not_called()
        import base64
        self.assertEqual(client.auth_key_hex, base64.b64decode("bmV3X2F1dGhfa2V5").hex())
        self.assertEqual(client.viewer_id, 5390138731907)

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_login_persists_hex_auth_key_after_transition(self, mock_unpack_func, mock_session_cls, _mock_pack):
        import base64
        import json

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({
            "viewer_id": 5390138731907,
            "auth_key": "66616b655f617574685f6b6579",
            "steam_username": "test_user",
            "steam_password_seed": "test_pass",
        })
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()
        new_b64 = "bmV3X2F1dGhfa2V5"
        new_hex = base64.b64decode(new_b64).hex()

        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 1}, "data": {"viewer_id": 5390138731907, "auth_key": new_b64}},
            {"data_headers": {"result_code": 1}, "data": {"viewer_id": 5390138731907, "auth_key": new_b64}},
            {"data_headers": {"result_code": 1, "viewer_id": 5390138731907, "sid": "MOCK_NEW_SID_HEX"}, "data": {}},
            {"data_headers": {"result_code": 1, "viewer_id": 5390138731907}, "data": {"tp_info": {"current_tp": 100}}},
        ]

        with TemporaryDirectory() as tmp_dir:
            cache = Path(tmp_dir) / "auth_cache.json"
            cache.write_text('{"uma_password_hash":"pw_hash","viewer_id":1}', encoding="utf-8")
            with patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
                client.login(max_retries=1)
            saved = json.loads(cache.read_text(encoding="utf-8"))

        self.assertEqual(saved["auth_key"], new_hex)
        self.assertEqual(saved["viewer_id"], 5390138731907)
        self.assertEqual(client.auth_key_hex, new_hex)

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_call_501_adopts_live_viewer_id_before_relogin(self, mock_unpack_func, mock_session_cls, _mock_pack):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({"viewer_id": 111, "auth_key": "66616b655f617574685f6b6579"})
        client = UmaClient(self.cfg, trace_enabled=False)
        client._refresh_ticket_and_login = MagicMock()
        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501, "viewer_id": 5148205094327}, "data": {}},
            {"data_headers": {"result_code": 1, "viewer_id": 5148205094327}, "data": {}},
        ]

        client.call("load/index", {"adid": ""})

        self.assertEqual(client.viewer_id, 5148205094327)
        self.assertEqual(client._cfg["viewer_id"], 5148205094327)
        client._refresh_ticket_and_login.assert_called_once_with()

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_login_fails_fast_when_start_session_501_has_no_transition_hash(self, mock_unpack_func, mock_session_cls, _mock_pack):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({
            "viewer_id": 5390138731907,
            "auth_key": "66616b655f617574685f6b6579",
            "steam_username": "test_user",
            "steam_password_seed": "test_pass",
        })
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()
        # authed start 501 + anon start 501 → no password hash → fail
        mock_unpack_func.return_value = {"data_headers": {"result_code": 501}, "data": {}}

        with TemporaryDirectory() as tmp_dir:
            with patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
                with self.assertRaisesRegex(Exception, "no uma_password_hash"):
                    client.login(max_retries=3)

        # One authed start_session + one anonymous start_session before fail.
        self.assertEqual(mock_session.post.call_count, 2)
        client.signup.assert_not_called()

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_login_does_not_recurse_on_transition_501(self, mock_unpack_func, mock_session_cls, _mock_pack):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({
            "viewer_id": 5390138731907,
            "auth_key": "66616b655f617574685f6b6579",
            "steam_username": "test_user",
            "steam_password_seed": "test_pass",
        })
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()
        # authed start 501 → anon start 501 → chain 501 (fully invalidated)
        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 501}, "data": {}},
        ]

        with TemporaryDirectory() as tmp_dir:
            cache = Path(tmp_dir) / "auth_cache.json"
            cache.write_text('{"uma_password_hash":"pw_hash"}', encoding="utf-8")
            with patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
                with self.assertRaisesRegex(Exception, "session fully invalidated"):
                    client.login(max_retries=3)

        posted_urls = [call.args[0] for call in mock_session.post.call_args_list]
        # Exactly one chain attempt; no get_by_transition after chain 501.
        self.assertEqual(sum(url.endswith("account/chain_by_transition_code") for url in posted_urls), 1)
        self.assertFalse(any(url.endswith("account/get_by_transition_code") for url in posted_urls))
        client.signup.assert_not_called()

    @patch('uma_api.client.pack', return_value=b'body')
    @patch('uma_api.client.requests.Session')
    @patch('uma_api.client.unpack')
    def test_transition_calls_use_anonymous_viewer_header(self, mock_unpack_func, mock_session_cls, mock_pack):
        """Working game captures send ViewerID=0 + empty auth on chain/get_by_transition."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock(status_code=200, text="dummy_response_text")
        mock_session.post = MagicMock(return_value=mock_response)

        self.cfg.update({
            "viewer_id": 1122334455,
            "auth_key": "66616b655f617574685f6b6579",
            "steam_username": "test_user",
            "steam_password_seed": "test_pass",
        })
        client = UmaClient(self.cfg, trace_enabled=False)
        client.signup = MagicMock()

        # start_session 501 -> anonymous start_session 501 -> chain OK -> get OK -> start OK -> load OK
        mock_unpack_func.side_effect = [
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 501}, "data": {}},
            {"data_headers": {"result_code": 1}, "data": {"target_viewer_id": 1122334455}},
            {"data_headers": {"result_code": 1}, "data": {"target_viewer_id": 1122334455, "auth_key": "bmV3X2F1dGhfa2V5"}},
            {"data_headers": {"result_code": 1, "viewer_id": 1122334455, "sid": "MOCK_SID"}, "data": {}},
            {"data_headers": {"result_code": 1, "viewer_id": 1122334455}, "data": {"tp_info": {"current_tp": 7}}},
        ]

        with TemporaryDirectory() as tmp_dir:
            cache = Path(tmp_dir) / "auth_cache.json"
            cache.write_text('{"uma_password_hash":"pw_hash","viewer_id":1122334455}', encoding="utf-8")
            with patch("uma_api.client.runtime_output_root", return_value=Path(tmp_dir)):
                res = client.login(max_retries=3)

        # Inspect pack() auth args and post headers for transition endpoints.
        posted = mock_session.post.call_args_list
        packed = mock_pack.call_args_list
        # map by order: start, start(anon), chain(anon), get(anon), start(anon), load(anon)
        urls = [c.args[0] for c in posted]
        self.assertTrue(any(u.endswith("account/chain_by_transition_code") for u in urls))
        self.assertTrue(any(u.endswith("account/get_by_transition_code") for u in urls))

        for call in posted:
            url = call.args[0]
            headers = call.kwargs.get("headers") or (call.args[2] if len(call.args) > 2 else {})
            # requests Session.post(url, data=..., headers=...)
            if not headers and "headers" in (call.kwargs or {}):
                headers = call.kwargs["headers"]
            # extract from kwargs always
            headers = call.kwargs.get("headers", headers)
            if any(url.endswith(ep) for ep in (
                "account/chain_by_transition_code",
                "account/get_by_transition_code",
                "tool/start_session",
            )):
                # Only assert anonymous for transition; start_session after first 501 also anon.
                if "transition" in url:
                    self.assertEqual(str(headers.get("ViewerID")), "0", msg=f"{url} headers={headers}")

        # pack(sid, udid_raw, auth, payload, udid) — auth must be empty for transition.
        for c, url in zip(packed, urls):
            if "transition" in url:
                auth_arg = c.args[2]
                self.assertEqual(auth_arg, b"", msg=f"auth not empty for {url}")

        self.assertEqual(res["data"]["tp_info"]["current_tp"], 7)
        client.signup.assert_not_called()

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

    def test_refresh_index_state_only_refreshes_start_and_load(self):
        import main

        class Client:
            def __init__(self):
                self.calls = []
                self.refreshed = None

            def regen_sid(self):
                self.calls.append(("regen_sid", None))

            def call(self, endpoint, payload):
                self.calls.append((endpoint, payload))
                if endpoint == "load/index":
                    return {"data": {"tp_info": {"current_tp": 30}}}
                return {"data": {}}

            def refresh_cached_account_state(self, data):
                self.refreshed = data

            def read_info(self):
                raise AssertionError("refresh_index_state must not call read_info")

        client = Client()

        assert main.refresh_index_state(client) == {"data": {"tp_info": {"current_tp": 30}}}
        assert [call[0] for call in client.calls] == ["regen_sid", "tool/start_session", "load/index"]
        assert client.refreshed == {"tp_info": {"current_tp": 30}}

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
