# Triage Summary

## Ranked Issues

### 1. Polling loop never exits on a normal successful response (High confidence)

**Evidence:** `if result.progress > 1.0: break` uses strictly-greater-than. AlphaSense's documentation [1] is consistent and explicit that a response is complete when `progress` reaches 1.0, and the field is documented as bounded between 0 and 1 but it never legitimately exceeds 1.0. Under this condition, the loop's exit case is essentially unreachable on a
healthy run, so the script polls forever even after the real answer is ready.

**Fix:** `if result.progress >= 1.0: break`

**Maps directly to:** "it hangs forever."

### 2. No client-side timeout on the polling loop (High/Medium confidence)

**Evidence:** The `while True:` loop has no time budget or max-iteration cap. A genuinely stalled or slow-running query (the docs [2] note `deepResearch` can take 12–15 minutes) could hang the script indefinitely on the client side, with no way to distinguish if it is still working or actually stuck.

**Fix:** Track elapsed time against a `POLL_TIMEOUT_SECONDS` budget or raise/log and move to the next ticker if exceeded instead of looping forever.

**Maps to:** residual cases of "hangs forever" even once #1 is fixed, and contributes to "slower than docs say it should be" 

### 3. No exception handling around per-ticker API calls (High confidence)

**Evidence:** Nothing in `main()`'s loop is wrapped in a `try/except`. If `start_search()` or  `poll_conversation()` throws for any single ticker (expired token, transient network error, malformed response) the entire script terminates while the tickers already processed have files; however,
the failing ticker, and everything after it in the list do not.

**Fix:** Wrap each ticker's work in `try/except`, log the failure, and `continue` to the next ticker instead of letting one exception kill the batch.

**Maps directly to:** "it works for some tickers but not others."

### 4. Poll loop never inspects an error field (Medium confidence)

**Evidence:** The loop only reads `result.progress` and `result.markdown`. AlphaSense's conversation response includes an `error.code` field [3] that this script never checks. I can't fully confirm how this surfaces through the client's `poll_conversation()` wrapper, since the customer's `client.py` wasn't included; however, as written the script has no way to tell apart if something is still running, finished with nothing, and finished with an error.

**Fix:** Have `poll_conversation()` surface `error.code` and branch on it explicitly instead of relying on `if result and result.markdown` to infer what happened.

**Maps to:** Can map to client perceiving as a missing or wrong answer as no content is returned.

### 5. Output files silently overwrite on repeat runs (Low confidence as not a named complaint)

**Evidence:** `out_path = OUTPUT_DIR / f"{ticker}.md"` uses only the ticker as the filename, with no run timestamp. Running the script twice for the same ticker silently replaces the first output with no warning.

**Fix:** Include a run timestamp in the filename, or write to a per-run subfolder.

**Note:** Not one of the five reported complaints; however, worth mentioning as in case study 1 this is the same issue of silent data loss I encountered.

## Investigated and Ruled Out

- `TICKERS` list and imports syntax is correct; not a source of any complaint.

- `if result.progress < 0:` Progress is documented as bounded
  at a minimum of 0, so this branch is likely unreachable dead code, but it doesn't cause any of the reported symptoms.

- `OUTPUT_DIR.mkdir(exist_ok=True)` correct as written as it rules out a missing-directory crash as the cause of any complaint.

## API/LLM Behavior to Explain to the Client

**The citations are broken.** 

Very likely a format-expectations mismatch, not a bug. This script writes `result.markdown` to disk completely unprocessed. GenSearch responses follow a consistent markdown structure. Understanding this structure helps you parse, render, and extract data programmatically [4][5]. The client may not be familiar with the format. Also, would normally ask them to share the citations they are seeing to better understand what they are seeing to think it is broken.

***How I'd explain it:*** 

Show them the three documented citation formats,
and point out this is the raw, intentional format and that they will need to parse it explicitly to get clean source references.

**The answers are wrong.** 

Possibly a real bug, but I cannot confirm without a specific example from the client I'd ask for one before doing anything else here. Two known edge cases can contribute to this as seen in the docs [6], partial and truncated answers can occur. Partial answers can occur is progress is less then 1 and answers can get truncated as long deepSearch results can exceed internal length limits. In this case, progress can reach complete but the content retrieved may end abruptly. 

***How I'd explain it:*** 

Ask for one concrete example of an answer they believe is wrong, and in parallel suggest adding filters to narrow what the query grounds against.

**Slower than the docs say it should be.** 

Largely explained by issue #1; however, an infinite hang reads as "extremely slow" to a client who doesn't know the loop never terminates. Separately, the script never specifies a mode, so if the client's `AlphaSenseClient` uses `thinkLonger` or `deepResearch` rather than `auto` the expected duration itself would be longer than they assumed.

***How I'd explain it:*** 

Confirm which mode is used in their client wrapper and change it to the recommended mode auto [7].


### References: ### 
[1] https://developer.alpha-sense.com/agent-api/gensearch#full-polling-implementation

[2] https://developer.alpha-sense.com/agent-api/gensearch#mode-comparison

[3] https://developer.alpha-sense.com/agent-api/response-parsing#empty-results-no_docs-error-code 

[4] https://developer.alpha-sense.com/agent-api/response-parsing#markdown-structure

[5] https://developer.alpha-sense.com/agent-api/response-parsing#the-3-citation-formats

[6] https://developer.alpha-sense.com/agent-api/response-parsing#edge-cases

[7] https://developer.alpha-sense.com/agent-api/gensearch#mode-comparison 