## Correspondence ##

Hello my name is Ebrahim and it will be my pleasure to assist you with these issues you are having. From my understanding of the case notes, it seems you are encountering the multiple issues with your integration of GenSearch that was built on top of the AlphaSense Agent API. These are a few of the effects of the issues you are experiencing:

1. It hangs forever
2. The answers are wrong
3. It works for some tickers but not others
4. It's slower than the docs say it should be
5. The citations are broken

Also, you shared your integration script as an attachment on the case.

Please feel free to correct me in my understanding of the case details so far. 

I reviewed the integration script you shared and did not a few details that can contribute to these issues. First, in your integration script I see `if result.progress > 1.0: break` uses strictly-greater-than. AlphaSense's documentation [1] is consistent and explicit that a response is complete when `progress` reaches 1.0, and the field is documented as bounded between 0 and 1 but it never legitimately exceeds 1.0. Under this condition, the loop's exit case is essentially unreachable on a healthy run, so the script polls forever even after the real answer is ready. This can be fixed by using a greater or equal than instead.

In regards to the second effect, can you please share an example that you are seeing. The documentation [2], mentions of the edge cases of partial and truncated results. Partial results can show while progress is still less then 1 and results can be truncated if deep reseasrch responses exceed internal length limits which would cause results to abruptly end.

Thirdly, nothing in `main()`'s loop is wrapped in a `try/except` block. Due to this, if `start_search()` or  `poll_conversation()` throw for any single ticker (for reasons like expired token, transient network error, malformed response) the entire script terminates. This would cause the tickers that already finished processing to have files and the others to not have files which can make it appear it works for some tickers but not all. A way to circumnavigate this is to wrap each ticker in a `try/except` block, log the error, and add a `continue` to move on to the next ticker. 

In regards to the fourth effect you see, I noticed that the `while True;` loop in your script does not have a time budget. This can cause the script to hang because of that. The documentation [3], also mentions that `deepResearch` can take 12-15minutes. A way around this is to add a `POLL_TIMEOUT_SECONDS` budget to this loop and add a failure/log then move on to the next ticket. As currently it just loops without any timeouts which can make it take longer then documentation mentions. Also, in the script I do not see a mode explicitly mentioned I suggest implementing auto mode as if using `deepResearch` or `thinkLonger` that may be why you are seeing it take long.

Finally, in regards to the citations being broken can you please share how they are broken as well as an example. The script writes `result.markdown` to the disk completely unprocessed. GenSearch responses follow a consistent markdown structure that is outpligned in the reference documents [4][5]. Also, please see reference document [6] for an example of how to render citations for all three formats mentioned in [5].  

I hope this helps with your concerns and the issues you have been experiencing. I would also be happy to jump on a call with you if you would like me to explain these findings even further. Please let me know if you have any other questions or need any other assistance. Have a wonderful day.

### References ###

[1] https://developer.alpha-sense.com/agent-api/gensearch#full-polling-implementation

[2] https://developer.alpha-sense.com/agent-api/response-parsing#edge-cases

[3] https://developer.alpha-sense.com/agent-api/gensearch#mode-comparison

[4] https://developer.alpha-sense.com/agent-api/response-parsing#markdown-structure

[5] https://developer.alpha-sense.com/agent-api/response-parsing#the-3-citation-formats

[6] https://developer.alpha-sense.com/agent-api/response-parsing#rendering-citations 
