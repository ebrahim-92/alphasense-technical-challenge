#!/usr/bin/env python3
"""
test for monitor.py
============================

WHAT THIS DOES:
Runs monitor script's full logic (login, ask a question, poll, parse
citations, save files, remember state, ask a follow-up next time) without
calling the real AlphaSense API. Instead it swaps out `requests.post` for a
fake version that returns realistic-looking responses.

"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

# Fake credentials which are good enough to satisfy os.environ lookups without
# ever touching the real API.
import os
os.environ.setdefault("ALPHASENSE_API_KEY", "fake-key")
os.environ.setdefault("ALPHASENSE_CLIENT_ID", "fake-client-id")
os.environ.setdefault("ALPHASENSE_CLIENT_SECRET", "fake-secret")
os.environ.setdefault("ALPHASENSE_EMAIL", "fake@example.com")
os.environ.setdefault("ALPHASENSE_PASSWORD", "fake-password")

import case_study1.monitor as monitor  


class FakeResponse:
    """Stands in for requests.Response """
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"Fake HTTP {self.status_code}")

    def json(self):
        return self._json_data


class FakeAlphaSense:
    """
    A fake AlphaSense server. Each ticker gets one "in-progress" poll
    response (progress 0.5) followed by a "done" response (progress 1.0)
    this specifically exercises the polling loop.
    """
    def __init__(self):
        self.poll_call_count = {}

    def post(self, url, headers=None, data=None, json=None, timeout=None):
        # --- Auth endpoint ---
        if url == monitor.AUTH_URL:
            return FakeResponse({"access_token": "fake-token-123"})

        # --- GraphQL endpoint ---
        query = json["query"]
        variables = json.get("variables", {})

        if "auto(input: $input)" in query:
            # A fresh question OR a follow-up (follow-up just has
            # conversationId set inside variables["input"])
            is_followup = bool(variables["input"].get("conversationId"))
            conv_id = "conv-followup-999" if is_followup else "conv-initial-123"
            return FakeResponse({"data": {"genSearch": {"auto": {"id": conv_id}}}})

        if "conversation(id: $conversationId)" in query:
            conv_id = variables["conversationId"]
            self.poll_call_count[conv_id] = self.poll_call_count.get(conv_id, 0) + 1

            if self.poll_call_count[conv_id] == 1:
                # First poll: still in progress this is what makes sure
                # the loop actually loops instead of assuming one call is enough.
                return FakeResponse({
                    "data": {"genSearch": {"conversation": {
                        "markdown": None, "progress": 0.5, "error": None,
                    }}}
                })

            # Second poll: done, with citations in all three formats
            if conv_id == "conv-initial-123":
                markdown = (
                    "Revenue grew 6% YoY [[38 • 10-K]](https://research.alpha-sense.com"
                    "?docid=V00001234&page=29) and Services hit a record "
                    "[[311]](https://research.alpha-sense.com?docid=V00001234&page=31)."
                )
            else:
                markdown = (
                    "Since last check, guidance was raised "
                    "[[312] 10-K • Test Corp • 1 Jan 26 • \"Update\"]"
                    "(https://research.alpha-sense.com?docid=V00005678&page=12)."
                )
            return FakeResponse({
                "data": {"genSearch": {"conversation": {
                    "markdown": markdown, "progress": 1.0, "error": None,
                }}}
            })

        raise AssertionError(f"Unexpected query sent to fake server: {query[:80]}")


def run_test():
    # Uses a throwaway folder so this never touches the real reports/state
    test_dir = Path("test_run_output")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir()

    monitor.REPORTS_DIR = test_dir / "reports"
    monitor.STATE_DIR = test_dir / "state"
    monitor.TICKERS = ["TEST"]
    monitor.POLL_INTERVAL_SECONDS = 0  

    fake_server = FakeAlphaSense()

    print("=" * 60)
    print("RUN 1 — first pass, no prior state")
    print("=" * 60)
    with patch("requests.post", side_effect=fake_server.post):
        monitor.main()

    state_file = monitor.STATE_DIR / "state.json"
    assert state_file.exists(), "FAIL: state.json was not created"
    state = json.loads(state_file.read_text())
    assert state["TEST"]["conversation_id"] == "conv-initial-123", "FAIL: wrong conversation_id saved"
    print("\nPASS: state.json correctly saved the conversation ID from run 1.\n")

    print("=" * 60)
    print("RUN 2 — should detect prior state and ask a follow-up")
    print("=" * 60)
    with patch("requests.post", side_effect=fake_server.post):
        monitor.main()

    state = json.loads(state_file.read_text())
    assert state["TEST"]["conversation_id"] == "conv-followup-999", "FAIL: run 2 did not use follow-up"
    print("\nPASS: run 2 correctly reused conversation state and asked a follow-up.\n")

    reports = list((test_dir / "reports").glob("TEST_*.md"))
    refs = list((test_dir / "reports").glob("TEST_*_references.json"))
    assert len(reports) == 2, f"FAIL: expected 2 report files, found {len(reports)}"
    assert len(refs) == 2, f"FAIL: expected 2 references files, found {len(refs)}"
    print(f"PASS: {len(reports)} markdown reports and {len(refs)} reference files saved.\n")

    # Check citation parsing on the first run's output
    first_refs = json.loads(sorted(refs)[0].read_text())
    assert len(first_refs) == 2, f"FAIL: expected 2 citations in run 1, found {len(first_refs)}"
    assert first_refs[0]["docid"] == "V00001234", "FAIL: docid not extracted correctly"
    print("PASS: citations parsed correctly, including docid/page extraction.\n")

    print("=" * 60)
    print("ALL CHECKS PASSED")
    print("=" * 60)
    print(f"\nInspect the fake output yourself in: {test_dir}/")
    print("(This folder is safe to delete — it's test data, not real API results.)")


if __name__ == "__main__":
    run_test()
