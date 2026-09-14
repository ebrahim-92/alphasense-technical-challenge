"""
Batch GenSearch report generator.
Loops over a list of tickers, runs a GenSearch query for each, and saves results to markdown
files.
"""
import time
from pathlib import Path
# The client code here implements authentication and search with status polling
from client import AlphaSenseClient
TICKERS = ["AAPL"
"MSFT"
,
,
POLL_INTERVAL = 2.0
OUTPUT_DIR = Path("reports")
"NVDA"
"GOOGL"
,
,
"AMZN"]
def build_prompt(ticker: str) -> str:
return f"Summarize the latest financial performance and analyst outlook for {ticker}.
"
def main() -> None:
client = AlphaSenseClient()
client.authenticate()
OUTPUT_DIR.mkdir(exist_ok=True)
for ticker in TICKERS:
print(f"\n[{ticker}] Submitting query...
prompt = build_prompt(ticker)
")
conv_id = client.start_search(prompt)
print(f"[{ticker}] Conversation ID: {conv_id}")
result = None
while True:
result = client.poll_conversation(conv_id)
print(f"[{ticker}] Progress: {result.progress:.0%}")
if result.progress < 0:
print(f"[{ticker}] Unexpected progress value, skipping.
break
")
if result.progress > 1.0:
break
time.sleep(POLL_INTERVAL)
if result and result.markdown:
out_path = OUTPUT_DIR / f"{ticker}.md"