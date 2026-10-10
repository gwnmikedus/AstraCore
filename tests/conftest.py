import os
import tempfile

# Isolated database for tests - never touch the real data/ directory.
os.environ.setdefault("PI_PLANNER_DATA", tempfile.mkdtemp(prefix="pi_planner_test_"))

from pi_planner import db  # noqa: E402

db.init()
