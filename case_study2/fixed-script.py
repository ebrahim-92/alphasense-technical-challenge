"""
Batch GenSearch report generator.
Loops over a list of tickers, runs a GenSearch query for each, and saves results to markdown
files.
"""
import time
from pathlib import Path

# The client code here implements authentication and search with status polling
from client import AlphaSenseClient

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
POLL_INTERVAL = 2.0
POLL_TIMEOUT_SECONDS = 120  # FIX: give up after this long instead of polling forever
OUTPUT_DIR = Path("reports")


def build_prompt(ticker: str) -> str:
    return f"Summarize the latest financial performance and analyst outlook for {ticker}."


def main() -> None:
    client = AlphaSenseClient()
    client.authenticate()
    OUTPUT_DIR.mkdir(exist_ok=True)

    for ticker in TICKERS:
        # FIX: each ticker is now isolated in its own try/except so one failure
        # (expired token, transient network error, malformed response) doesn't
        # kill the whole batch and leave later tickers unprocessed.
        try:
            print(f"\n[{ticker}] Submitting query...")
            prompt = build_prompt(ticker)
            conv_id = client.start_search(prompt)
            print(f"[{ticker}] Conversation ID: {conv_id}")

            result = None
            deadline = time.time() + POLL_TIMEOUT_SECONDS  # FIX: bounded wait

            while True:
                result = client.poll_conversation(conv_id)
                print(f"[{ticker}] Progress: {result.progress:.0%}")

                # FIX: surface an error state explicitly instead of only
                # inferring failure later from a missing markdown field.
                # getattr is used defensively since the error field's exact
                # shape on `result` wasn't visible in the provided snippet.
                error = getattr(result, "error", None)
                if error:
                    print(f"[{ticker}] GenSearch returned an error: {error}. Skipping.")
                    result = None
                    break

                if result.progress < 0:
                    print(f"[{ticker}] Unexpected progress value, skipping.")
                    result = None
                    break

                # FIX: was `> 1.0` (strictly greater-than), which is
                # essentially unreachable since progress is documented as
                # bounded between 0 and 1.0. A healthy completed run never
                # exceeds 1.0, so the loop never exited and the script hung
                # forever. Corrected to `>= 1.0` to match the documented
                # completion condition.
                if result.progress >= 1.0:
                    break

                # FIX: enforce the timeout budget instead of looping forever
                # if a query genuinely stalls.
                if time.time() > deadline:
                    print(f"[{ticker}] Timed out after {POLL_TIMEOUT_SECONDS}s, skipping.")
                    result = None
                    break

                time.sleep(POLL_INTERVAL)

            if result and result.markdown:
                out_path = OUTPUT_DIR / f"{ticker}.md"
                out_path.write_text(result.markdown, encoding="utf-8")
                print(f"[{ticker}] Saved -> {out_path}")
            else:
                print(f"[{ticker}] No content returned, skipping.")

        except Exception as e:
            # FIX: catch and log per-ticker failures instead of letting them
            # crash the whole batch.
            print(f"[{ticker}] FAILED: {e}. Continuing with next ticker.")
            continue


if __name__ == "__main__":
    main()