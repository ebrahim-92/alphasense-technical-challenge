#!/usr/bin/env python3
"""
GenSearch Ticker Monitor
=========================

Tracks a set of tickers via AlphaSense GenSearch. First run asks a broad
question per ticker; later runs ask a follow-up ("what's changed?") in the
same conversation thread using conversationId. Citations are parsed out
of the markdown into a separate references file.

"""

import os
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import requests

# ---------------------------------------------------------------------------
# SETTINGS — the things you're most likely to want to change
# ---------------------------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "NVDA"]   # which companies to track
POLL_INTERVAL_SECONDS = 3            # how often to check if the answer is ready
POLL_TIMEOUT_SECONDS = 120           # give up after this long 

STATE_DIR = Path("state")            # remembers the last conversation per ticker
REPORTS_DIR = Path("reports")        # where each answer gets saved

AUTH_URL = "https://api.alpha-sense.com/auth"
GRAPHQL_URL = "https://api.alpha-sense.com/gql"


# ---------------------------------------------------------------------------
# STEP 1 — LOG IN
# This trades your username/password for a temporary "access token" that
# proves who you are on every later request.
# ---------------------------------------------------------------------------
def authenticate() -> str:
    response = requests.post(
        AUTH_URL,
        headers={
            "x-api-key": os.environ["ALPHASENSE_API_KEY"],
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "password",
            "username": os.environ["ALPHASENSE_EMAIL"],
            "password": os.environ["ALPHASENSE_PASSWORD"],
            "client_id": os.environ["ALPHASENSE_CLIENT_ID"],
            "client_secret": os.environ["ALPHASENSE_CLIENT_SECRET"],
        },
        timeout=30,
    )
    response.raise_for_status()  
    return response.json()["access_token"]


def gql_headers(access_token: str) -> dict:
    return {
        "x-api-key": os.environ["ALPHASENSE_API_KEY"],
        "clientid": os.environ["ALPHASENSE_CLIENT_ID"],
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Small helper used by every API call below.
# IMPORTANT DETAIL: a GraphQL API can fail in a way a normal web request
# doesn't as it can return a perfectly healthy "200 OK" but with an "errors"
# field instead of real data. If we don't check for that, the script would
# crash later with a confusing "NoneType" error instead of telling you what
# actually went wrong. This function catches that.
# ---------------------------------------------------------------------------
def post_graphql(access_token: str, query: str, variables: dict | None = None) -> dict:
    response = requests.post(
        GRAPHQL_URL,
        headers=gql_headers(access_token),
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL returned an error: {payload['errors'][0].get('message')}")
    return payload["data"]


# ---------------------------------------------------------------------------
# STEP 2 — ASK A QUESTION
# This starts a GenSearch query in "auto" mode; however, it does not return the answer yet as GenSearch takes a
# few seconds to research and write the answer, so this call just returns a
# "conversationId" that we can use to check on progress.
#
# If conversation_id is provided, this asks a follow-up question in the same
# thread instead of starting fresh as AlphaSense remembers the earlier
# context so "what's changed?" makes sense as a question.
# ---------------------------------------------------------------------------
def ask_gensearch(access_token: str, prompt: str, conversation_id: str | None = None) -> str:
    # There is only one mutation ("auto") for both a fresh question and a
    # follow-up, what makes it a follow-up is simply including the previous
    # conversationId inside the input object. Leaving conversationId out (or
    # None) starts a brand new, unrelated conversation.
    mutation = """
    mutation GenSearchAuto($input: GenSearchInput!) {
      genSearch {
        auto(input: $input) {
          id
        }
      }
    }
    """
    input_obj = {"prompt": prompt}
    if conversation_id:
        input_obj["conversationId"] = conversation_id

    data = post_graphql(access_token, mutation, {"input": input_obj})
    return data["genSearch"]["auto"]["id"]


# ---------------------------------------------------------------------------
# STEP 3 — WAIT FOR THE ANSWER
# GenSearch writes the answer gradually. It does this by polling and stops when:
#   - progress reaches 1.0 (done), OR
#   - an error comes back (e.g. NO_DOCS — AlphaSense found nothing relevant), OR
#   - we've waited too long (POLL_TIMEOUT_SECONDS)
# ---------------------------------------------------------------------------
def poll_until_done(access_token: str, conversation_id: str) -> str:
    query = """
    query Poll($conversationId: String!) {
      genSearch {
        conversation(id: $conversationId) {
          markdown
          progress
          error { code }
        }
      }
    }
    """
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        data = post_graphql(access_token, query, {"conversationId": conversation_id})
        conv = data["genSearch"]["conversation"]

        if conv.get("error"):
            code = conv["error"]["code"]
            if code == "NO_DOCS":
                raise RuntimeError(
                    "AlphaSense found no relevant documents for this query (NO_DOCS). "
                    "Try broadening the question or picking a different ticker."
                )
            raise RuntimeError(f"GenSearch returned an error: {code}")

        print(f"    progress: {conv['progress']:.0%}")
        if conv["progress"] >= 1.0:
            return conv["markdown"]

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Gave up waiting after {POLL_TIMEOUT_SECONDS}s. "
        "The query may still be running on AlphaSense's side — try polling longer."
    )


# ---------------------------------------------------------------------------
# STEP 4 — PULL OUT THE CITATIONS
# GenSearch answers contain inline citation links like:
#   [[38 • 10-K]](https://research.alpha-sense.com?docid=V00001234&page=29)
# This pulls every citation out into a clean list (number, source, doc id,
# page) so you can show "sources" separately instead of
# leaving raw markdown links buried in the text.
# ---------------------------------------------------------------------------
# AlphaSense uses three citation link shapes in GenSearch markdown:
#   1. Short name:    [[38 • 10-K]](url)
#   2. Number-only:    [[311]](url)               <- repeated references
#   3. Full metadata:  [[312] 10-K • Apple Inc. • 30 Oct 25 • "Annual Report"](url)
SHORT_PATTERN = re.compile(r"\[\[(\d+)\s*•\s*([^\]]+)\]\]\((https?://[^\)]+)\)")
NUMBER_PATTERN = re.compile(r"\[\[(\d+)\]\]\((https?://[^\)]+)\)")
FULL_PATTERN = re.compile(r"\[\[(\d+)\]\s*([^\]]+)\]\((https?://[^\)]+)\)")

def _doc_and_page(url: str) -> tuple[str | None, str | None]:
    params = parse_qs(urlparse(url).query)
    return params.get("docid", [None])[0], params.get("page", [None])[0]

def extract_citations(markdown: str) -> list[dict]:
    citations = []
    seen = set()

    for number, source, url in SHORT_PATTERN.findall(markdown):
        key = (number, url)
        if key in seen:
            continue
        seen.add(key)
        docid, page = _doc_and_page(url)
        citations.append({"number": number, "source": source.strip(), "url": url, "docid": docid, "page": page})

    for number, url in NUMBER_PATTERN.findall(markdown):
        key = (number, url)
        if key in seen:
            continue
        seen.add(key)
        docid, page = _doc_and_page(url)
        citations.append({"number": number, "source": "", "url": url, "docid": docid, "page": page})

    for number, source, url in FULL_PATTERN.findall(markdown):
        key = (number, url)
        if key in seen:
            continue
        seen.add(key)
        docid, page = _doc_and_page(url)
        citations.append({"number": number, "source": source.strip(), "url": url, "docid": docid, "page": page})

    return citations


# ---------------------------------------------------------------------------
# STEP 5 — REMEMBER STATE
# We save the conversationId for each ticker to a small JSON file. Next run,
# if we already have a conversationId for a ticker, we ask a follow-up
# instead of starting a brand new conversation.
# ---------------------------------------------------------------------------
def load_state() -> dict:
    STATE_DIR.mkdir(exist_ok=True)
    state_file = STATE_DIR / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}

def save_state(state: dict) -> None:
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# PUTTING IT ALL TOGETHER
# ---------------------------------------------------------------------------
def main():
    REPORTS_DIR.mkdir(exist_ok=True)
    print("Logging in...")
    access_token = authenticate()
    print("Logged in.\n")

    state = load_state()

    for ticker in TICKERS:
        print(f"[{ticker}]")
        previous_conversation_id = state.get(ticker, {}).get("conversation_id")

        if previous_conversation_id:
            prompt = f"What has changed for {ticker} since we last checked?"
            print(f"  Following up on previous conversation...")
        else:
            prompt = f"Summarize the latest financial performance and analyst outlook for {ticker}."
            print(f"  Starting a new conversation...")

        conversation_id = ask_gensearch(access_token, prompt, previous_conversation_id)
        print(f"  Conversation ID: {conversation_id}")

        try:
            markdown = poll_until_done(access_token, conversation_id)
        except (RuntimeError, TimeoutError) as e:
            print(f"  FAILED: {e}\n")
            continue

        citations = extract_citations(markdown)

        # Save the answer
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        report_path = REPORTS_DIR / f"{ticker}_{timestamp}.md"
        report_path.write_text(markdown)

        # Save the citations separately, as required by the assignment
        refs_path = REPORTS_DIR / f"{ticker}_{timestamp}_references.json"
        refs_path.write_text(json.dumps(citations, indent=2))

        print(f"  Saved answer  -> {report_path}")
        print(f"  Saved sources -> {refs_path} ({len(citations)} citations)\n")

        # Remember this conversation for next time
        state[ticker] = {"conversation_id": conversation_id, "last_run": timestamp}
        save_state(state)

    print("Done.")


if __name__ == "__main__":
    main()
