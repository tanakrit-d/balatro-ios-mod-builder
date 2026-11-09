import http.client
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ios_openssl


class OpenSSLDownloadTests(unittest.TestCase):
    def response(self, data=b"archive"):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = data
        return response

    @patch("ios_openssl.time.sleep")
    @patch("ios_openssl.urllib.request.urlopen")
    def test_gateway_timeout_then_success(self, urlopen, sleep):
        error = urllib.error.HTTPError(
            "https://example.com", 504, "timeout", {}, io.BytesIO()
        )
        urlopen.side_effect = [error, self.response()]
        self.assertEqual(ios_openssl.download(ios_openssl.SOURCE_URL), b"archive")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2)

    @patch("ios_openssl.time.sleep")
    @patch("ios_openssl.urllib.request.urlopen")
    def test_transient_failures_are_bounded(self, urlopen, sleep):
        for error in (
            urllib.error.HTTPError("https://example.com", 503, "unavailable", {}, None),
            urllib.error.URLError("connection failed"),
            TimeoutError("timed out"),
            ConnectionResetError("reset"),
            http.client.IncompleteRead(b"partial", 100),
        ):
            with self.subTest(error=error):
                urlopen.reset_mock()
                sleep.reset_mock()
                urlopen.side_effect = error
                with self.assertRaises(type(error)):
                    ios_openssl.download(ios_openssl.SOURCE_URL)
                self.assertEqual(urlopen.call_count, 4)
                self.assertEqual(sleep.call_args_list, [call(2), call(4), call(8)])

    @patch("ios_openssl.time.sleep")
    @patch("ios_openssl.urllib.request.urlopen")
    def test_not_found_is_not_retried(self, urlopen, sleep):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 404, "missing", {}, None
        )
        with self.assertRaises(urllib.error.HTTPError):
            ios_openssl.download(ios_openssl.SOURCE_URL)
        urlopen.assert_called_once()
        sleep.assert_not_called()

    @patch("ios_openssl.time.sleep")
    @patch("ios_openssl.urllib.request.urlopen")
    def test_read_failure_discards_partial_response(self, urlopen, sleep):
        response = self.response()
        response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(
            b"partial", 100
        )
        urlopen.side_effect = [response, self.response(b"complete")]
        self.assertEqual(ios_openssl.download(ios_openssl.SOURCE_URL), b"complete")
        response.__exit__.assert_called_once()

    @patch("ios_openssl.urllib.request.urlopen")
    def test_source_checksum_still_required(self, urlopen):
        urlopen.return_value = self.response(b"invalid source")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "checksum mismatch"),
        ):
            ios_openssl.build(Path(directory))

    @patch("ios_openssl.download", side_effect=TimeoutError("timed out"))
    def test_failed_download_does_not_cache_archive(self, download):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            with self.assertRaises(TimeoutError):
                ios_openssl.build(work)
            self.assertFalse((work / "openssl.tar.gz").exists())
