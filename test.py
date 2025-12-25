# local_test.py

import io
import json
from func import handler  # import your existing handler from func.py


class DummyCtx:
    """
    Minimal context object to satisfy fdk.response.Response,
    which expects SetResponseHeaders on the ctx.
    """

    def __init__(self):
        self.request_id = "local-test"
        self._headers = {}
        self._status_code = 200

    def SetResponseHeaders(self, headers, status_code):
        """Called by fdk.response.Response.__init__()."""
        self._headers = headers or {}
        self._status_code = status_code

    # Optional helpers if you want to inspect them later
    def ResponseHeaders(self):
        return self._headers

    def StatusCode(self):
        return self._status_code


if __name__ == "__main__":
    # Change this query to test different questions
    payload = {
        "query": "Show total purchase order amount by month for 2024"
    }

    # Create a BytesIO stream like Fn would pass into handler
    data = io.BytesIO(json.dumps(payload).encode("utf-8"))

    # Use DummyCtx instead of real Fn context
    ctx = DummyCtx()

    # Call your function's handler
    resp = handler(ctx, data)

    # fdk Response object usually has .body (bytes)
    if hasattr(resp, "body"):
        # Decode bytes to string if needed
        body = resp.body.decode("utf-8") if isinstance(resp.body, (bytes, bytearray)) else resp.body
        print("Status code:", ctx.StatusCode())
        print("Headers:", json.dumps(ctx.ResponseHeaders(), indent=2))
        print("Body:", body)
    else:
        # If you return something else, just print it
        print(resp)
