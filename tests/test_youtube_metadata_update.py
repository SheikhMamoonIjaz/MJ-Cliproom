"""Updating published Shorts preserves their category/language and never calls the real YouTube API."""
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.update(PEAKCUT_DATA=tempfile.mkdtemp(prefix="mj-youtube-meta-"), DATABASE_URL="")
sys.path.insert(0, ".")
from studio import accounts


class Reply:
    def __init__(self, status, data):
        self.status_code, self.data = status, data
        self.headers, self.text = {}, ""

    def json(self):
        return self.data


calls = []


def get(url, *, params, headers, timeout):
    calls.append(("GET", url, params, headers, timeout))
    return Reply(200, {"items": [{"id": "abcdefghijk", "snippet": {
        "categoryId": "20", "defaultLanguage": "en"}}]})


def put(url, *, params, json, headers, timeout):
    calls.append(("PUT", url, params, json, headers, timeout))
    return Reply(200, json)


with patch.object(accounts, "_yt_token", return_value="test-token"), \
        patch.object(accounts.httpx, "get", side_effect=get), \
        patch.object(accounts.httpx, "put", side_effect=put):
    result = accounts.youtube_update_metadata(
        {"id": "yt_test", "platform": "youtube"}, "abcdefghijk", "A different clip title",
        "A unique description for this specific clip.", ["#GTA6", "#Shorts"])

assert result["id"] == "abcdefghijk"
assert len(calls) == 2 and calls[0][0] == "GET" and calls[1][0] == "PUT"
request = calls[1][3]
assert calls[1][2] == {"part": "snippet"}
assert request["id"] == "abcdefghijk"
assert request["snippet"] == {
    "title": "A different clip title", "description": "A unique description for this specific clip.",
    "tags": ["GTA6", "Shorts"], "categoryId": "20", "defaultLanguage": "en"}
assert "youtube.force-ssl" in accounts.YT_SCOPES
print("PASS updating published metadata preserves the video's category and language")
print("PASS expanded YouTube edit scope is requested on reconnect")

def denied_put(url, *, params, json, headers, timeout):
    return Reply(403, {"error": {"code": 403, "message": "insufficientPermissions"}})

with patch.object(accounts, "_yt_token", return_value="test-token"), \
        patch.object(accounts.httpx, "get", side_effect=get), \
        patch.object(accounts.httpx, "put", side_effect=denied_put):
    try:
        accounts.youtube_update_metadata(
            {"id": "yt_test", "platform": "youtube"}, "abcdefghijk", "A different clip title",
            "A unique description for this specific clip.", ["#GTA6", "#Shorts"])
    except ValueError as error:
        assert "Settings → Connected Apps" in str(error) and "youtube.force-ssl" in str(error)
    else:
        raise AssertionError("A rejected metadata permission did not provide reconnect instructions.")
print("PASS YouTube metadata permission errors explain the exact reconnect scope")
