"""arq job definitions.

Generation calls are slow and async (BUILD_PLAN Section 3), so they run here
rather than in a request. A job's provider call is recorded in the `job` table
from submit to outcome, whether or not it produced a `generation`.
"""
