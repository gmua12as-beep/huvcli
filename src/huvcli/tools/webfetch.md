Fetch a URL (GET only) and return its body as text.

HTML is stripped to plain text (no JavaScript rendering — script/style blocks are dropped, tags removed, entities unescaped). Body capped at ~100 KB by default.

Use for: official docs, READMEs, RFCs, package metadata pages. Don't use for sites that require auth, JS rendering, or interactive flows.

HTTP errors come back as readable text (`HTTP 404 Not Found for ...`) so you can recover and try a different URL.
