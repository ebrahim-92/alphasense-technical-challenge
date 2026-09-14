# GenSearch Ticker Monitor

## What this is and why I picked it

A small script that watches a handful of stock tickers using AlphaSense's
GenSearch API. The first run asks a broad question about each ticker's
recent financial performance; every run after that asks a targeted
follow-up ("what's changed since we last checked?") in the same
conversation thread, instead of repeating the full question from scratch.

I picked this shape over a one-shot CLI because it's closer to what a
support engineer actually deals with day to day which is not a single request, rather it is something running repeatedly over time. Where the state, incremental change, and "did this actually finish correctly" all matter.

## How to run it

1. Install the one dependency:
   ```
   pip install -r requirements.txt
   ```
2. Fill in the credentials for the .env file
   
3. Load the env vars and run:
   ```
   export $(grep -v '^#' .env | xargs)
   python3 monitor.py
   ```
4. Check the `reports/` folder where you will get one `.md` file which    contains the answer as well as one `_references.json` file which contains the parsed citations per ticker per run. 

To track different companies, edit the `TICKERS` list at the top of
`monitor.py`.

## Testing

The file test_monitor.py fakes AlphaSense's API responses by swapping out requests.post for a stand-in that returns canned data so the script's control flow consisting of auth handling, the polling loop, citation parsing, state persistence, and the first run vs follow-up branch can be verified without network access or real credentials. It does not and cannot verify that the real API behaves the way the docs describe; that's only confirmed by an actual live run.

This offline test is also what caught the bug described below, before any real credentials were involved.

## Design decisions

**Auto mode, not thinkLonger or deepResearch.** Auto is AlphaSense's own
recommended default and has the same credit cost as fast mode and it adapts depth to the question automatically. For a "what's changed" style question
that doesn't need report-grade output, `deepResearch`'s 12-15 minute
response time and 10x credit cost isn't worth it. This is information I obtained from this documentation: https://developer.alpha-sense.com/agent-api/gensearch#mode-comparison

**Polling instead of streaming.** Streaming would give a better UX for
anything a person is watching live, but this is a background job with no
one staring at the screen so polling every few seconds is simpler to
reason about and debug. Also, the credit/latency cost is the same either
way. This information was also determined via this documentation: https://developer.alpha-sense.com/agent-api/streaming#streaming-vs-polling

## What surprised me / what broke

Report filenames used the current time down to the second (e.g. TEST_180701.md). The offline test simulates two passes in a row which were an initial run and then a follow-up run. These were to check the script remembers prior state. Both passes landed in the same second which caused both files to get the same name which led to the second silently overwriting the first. Upon running the script it gave this error:

  File "/Users/ebrahim/Documents/AlphasenseTechnicalAssignment/test_monitor.py", line 157, in run_test
    assert len(reports) == 2, f"FAIL: expected 2 report files, found {len(reports)}"
AssertionError: FAIL: expected 2 report files, found 1

This error was not the most helpful as line 157 in the code was correct. I caught it by checking the output folder and finding one file where I expected two. I fixed this by adding microsecond precision to the timestamp by adding %f to the timestamp code so that near-simultaneous runs no longer collide. Bigger takeaway for "with another week" is that a run should never be able to silently destroy a previous one's data, regardless of timing.

## With another week

- Retry with backoff on the /auth call and on transient GraphQL errors

  As of now, if a request fails for a temporary reason such as a flaky connection or a momentary server hiccup the whole script just stops, even for tickers that would've worked fine on a second try. Most network failures are temporary and not permanent, so the script should wait a moment and try again (waiting a bit longer each retry) before giving up. This is the difference between a script that breaks on normal internet connectivity issues and one that shrugs it off.

- Structured storage (DynamoDB, S3 or a similar solution) instead of flat files

  Right now every run saves a new .md and .json file. That's fine for a few runs; however, if this is run daily for months you would have hundreds of loose files with no easy way to ask a question like "show me every time NVDA's outlook changed this year" as you would have to open files one by one. A real database lets you query the history instead of just piling it up.
