import os
import re
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

import requests

TICKERS = ["AAPL", "MSFT", "NVDA"]   
POLL_INTERVAL_SECONDS = 3            
POLL_TIMEOUT_SECONDS = 120            

STATE_DIR = Path("state")            
REPORTS_DIR = Path("reports")        

AUTH_URL = "https://api.alpha-sense.com/auth"
GRAPHQL_URL = "https://api.alpha-sense.com/gql"

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

def ask_gensearch(access_token: str, prompt: str, conversation_id: str | None = None) -> str:
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

def load_state() -> dict:
    STATE_DIR.mkdir(exist_ok=True)
    state_file = STATE_DIR / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}

def save_state(state: dict) -> None:
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))

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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        report_path = REPORTS_DIR / f"{ticker}_{timestamp}.md"
        report_path.write_text(markdown)
        refs_path = REPORTS_DIR / f"{ticker}_{timestamp}_references.json"
        refs_path.write_text(json.dumps(citations, indent=2))

        print(f"  Saved answer  -> {report_path}")
        print(f"  Saved sources -> {refs_path} ({len(citations)} citations)\n")
        state[ticker] = {"conversation_id": conversation_id, "last_run": timestamp}
        save_state(state)

    print("Done.")


if __name__ == "__main__":
    main()
