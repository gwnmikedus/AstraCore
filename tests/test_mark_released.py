"""`./astracore mark-released` (run by every deploy) keeps status:released = "live in production".

Runs against a throwaway git repo and a fake `gh` that records its calls, so nothing reaches GitHub."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "astracore"
FAKE_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view") case "$3" in 11) echo 21 ;; 12) printf '22\\n23\\n' ;; *) ;; esac ;;
  "issue list") printf '%s' "$SWEEP_ISSUES" ;;
  "api graphql") for a; do case "$a" in number=*) n=${a#number=} ;; esac; done; eval "v=\\$SHAS_$n"; printf '%s\\n' "$v" ;;
esac
"""

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.test")
    _git(root, "config", "user.name", "Test")
    shas = []
    for subject in ("chore: start", "feat: one (#11)", "docs: no pr", "fix: two (#12)", "feat: none closed (#13)"):
        _git(root, "commit", "-q", "--allow-empty", "-m", subject)
        shas.append(_git(root, "rev-parse", "HEAD"))
    shutil.copy(SCRIPT, root / "astracore")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    return root, shas, bin_dir, tmp_path / "gh.log"


def _run(root, bin_dir, log, *args, path=None, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASTRACORE_")}
    env.update(PATH=path or f"{bin_dir}:/usr/bin:/bin", GH_LOG=str(log), HOME=str(root.parent), **(extra or {}))
    return subprocess.run(["bash", str(root / "astracore"), "mark-released", *args], cwd=root, env=env,
                          capture_output=True, text=True, timeout=60, check=True)


def _edits(log):
    return [line for line in log.read_text().splitlines() if line.startswith("issue edit")] if log.exists() else []


def test_deploying_forward_marks_the_issues_its_prs_closed(repo):
    root, shas, bin_dir, log = repo
    out = _run(root, bin_dir, log, shas[0], shas[-1])
    assert sorted(_edits(log)) == [f"issue edit {n} --add-label status:released" for n in (21, 22, 23)]
    assert "Released: #21 (live through #11)" in out.stdout


def test_only_the_new_range_counts(repo):
    root, shas, bin_dir, log = repo
    _run(root, bin_dir, log, shas[2], shas[-1])      # #11 was already live
    assert sorted(_edits(log)) == [f"issue edit {n} --add-label status:released" for n in (22, 23)]


def test_rolling_back_removes_the_label(repo):
    root, shas, bin_dir, log = repo
    out = _run(root, bin_dir, log, shas[-1], shas[2])
    assert sorted(_edits(log)) == [f"issue edit {n} --remove-label status:released" for n in (22, 23)]
    assert "No longer released: #22 (#12 rolled back)" in out.stdout


def test_same_commit_does_nothing(repo):
    root, shas, bin_dir, log = repo
    _run(root, bin_dir, log, shas[-1], shas[-1])
    assert not log.exists()


@pytest.mark.skipif(shutil.which("gh", path="/usr/bin:/bin") is not None, reason="a system gh is installed")
def test_missing_gh_is_a_note_not_a_failure(repo, tmp_path):
    root, shas, _, log = repo
    out = _run(root, tmp_path, log, shas[0], shas[-1], path="/usr/bin:/bin")   # HOME has no .local/bin/gh either
    assert "gh not found" in out.stdout


def test_deploy_also_marks_issues_closed_by_hand_once_all_their_prs_are_live(repo):
    root, shas, bin_dir, log = repo
    _git(root, "commit", "-q", "--allow-empty", "-m", "feat: later, not deployed (#14)")
    later = _git(root, "rev-parse", "HEAD")
    sweep = {"SWEEP_ISSUES": "31\n32\n33\n", "SHAS_31": f"{shas[1]}\n{shas[3]}\n", "SHAS_32": f"{shas[1]}\n{later}\n",
             "SHAS_33": ""}
    out = _run(root, bin_dir, log, shas[2], shas[-1], extra=sweep)
    assert "issue edit 31 --add-label status:released" in _edits(log)     # both its PRs are in production
    assert not any(e.startswith("issue edit 32 ") for e in _edits(log))   # one PR merged but not deployed yet
    assert "Check by hand: #33" in out.stdout                             # closed without a merged pull request
    assert "Released: #31 (closed by hand; its pull requests are live)" in out.stdout


def test_rolling_back_does_not_sweep(repo):
    root, shas, bin_dir, log = repo
    _run(root, bin_dir, log, shas[-1], shas[2], extra={"SWEEP_ISSUES": "31\n", "SHAS_31": shas[1]})
    assert not any(e.startswith("issue edit 31 ") for e in _edits(log))
    assert "issue list" not in log.read_text()


def test_mark_released_without_a_range_sweeps_against_production(repo, tmp_path):
    root, shas, bin_dir, log = repo
    prod = tmp_path / "prod"
    _git(root, "worktree", "add", "-q", "--detach", str(prod), shas[3])
    out = _run(root, bin_dir, log, extra={"ASTRACORE_PROD_CHECKOUT": str(prod), "SWEEP_ISSUES": "31\n32\n",
                                          "SHAS_31": shas[1], "SHAS_32": shas[4]})
    assert _edits(log) == ["issue edit 31 --add-label status:released"]   # #13's commit isn't in production
    assert "Released: #31" in out.stdout
