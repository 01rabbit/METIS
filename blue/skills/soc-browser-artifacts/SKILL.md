---
name: soc-browser-artifacts
description: Analyze supplied browser history and download databases offline to reconstruct visits, redirects and downloaded artifacts. Does not operate a live browser console.
---

# Browser artifact analysis

For acquired Chromium History, Firefox places.sqlite, Safari history, extension/native-host
configuration or forensic-export schema candidates, use
[offline database analysis](references/history-downloads.md). Use soc-browser-console for
live UI work instead. Do not inspect the analyst's own browser profile as case evidence.

Preserve the database and available sidecars, identify schema/version, and declare row and
time limits. Correlate visits/downloads with filesystem and endpoint records. The existence
of a URL is not proof that a user typed it or that a download completed.

Report the original row/table coordinates, timestamp conversion, interpretation and gaps.
METIS's bounded [artifact reader](../../docs/artifact-tools.md) supports selected Chromium and
Firefox history tables in acquired SQLite/sidecar sets; check its schema and coverage limits.
Follow [the worker contract](../blue-owner/references/worker-contract.md).

For profile paths, database tables, URL-to-visit joins, redirect-chain ordering and timestamp
conversion, load the [browser schema worksheet](references/history-downloads.md) before querying.
Record browser family and profile separately so that identically numbered rows from different
profiles never become one timeline event.
