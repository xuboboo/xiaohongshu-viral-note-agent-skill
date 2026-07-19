# Hot ranking

Use `METRIC_HOT_SCORE` only when authorized interaction fields are present. Otherwise use
`PUBLIC_INDEX_HOT_SCORE`. Apply log scaling, freshness decay, creator-size normalization,
relevance and duplicate penalties. Never combine the score types without labeling them.
