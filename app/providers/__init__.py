"""Provider adapters — the ONLY package that may import a vendor SDK.

One module per capability, each implementing the protocol in BUILD_PLAN
Section 5: `ImageProvider`, `VideoProvider`, `VoiceProvider`, `LipSyncProvider`,
`LLMProvider`. Model ids, endpoints and prices come from
`config/providers.yaml` and are never written in code.

Every adapter reports the cost of a call that produced nothing (amendment A2).
A refusal after billing, a timeout, and a mid-generation failure all cost money;
an adapter that cannot tell a free failure from a billed one reports it as
billed, for the same reason the price convention takes the higher figure.

`Fake*` implementations live here too, and the pipeline must run end to end on
them before any paid call exists (task 0.6).
"""
