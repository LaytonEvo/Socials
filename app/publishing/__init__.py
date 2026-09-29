"""Platform exports and publication records.

**No publishing without a human.** A `publication` row cannot be created without
`ai_label_set = true` and a named approver, and the database enforces both. The
system never auto-posts.

Per amendment A10, the manual CSV path is the primary route: posting and
analytics APIs generally require app review or business-account status, and
access for a new small account is frequently refused. API ingestion is an
upgrade, never a dependency.
"""
