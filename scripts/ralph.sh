#!/bin/bash
# Ralph — autonomous AI agent loop
# Version: 2026.03.23.2248
#
# Passes all ralph:todo issues to a fresh agent instance, which chooses
# the best one to work on. Repeats until all issues are done.
#
# Usage: ./scripts/ralph.sh --milestone <name> [--iterations <n>]

RALPH_VERSION="2026.03.24.1418"

set -e

# ── Parse arguments ──────────────────────────────────────────────

MILESTONE=""
MAX_ITERATIONS=10
MODEL="claude-sonnet-4-6"
VERBOSE=false
TOOL_COMMAND="claude"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKING_PATH="$(pwd)"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"

while [[ $# -gt 0 ]]; do
  case $1 in
    --version)     echo "Ralph v$RALPH_VERSION"; exit 0 ;;
    --verbose|-v)  VERBOSE=true;              shift   ;;
    --milestone)   MILESTONE="$2";           shift 2 ;;
    --milestone=*) MILESTONE="${1#*=}";      shift   ;;
    --iterations)  MAX_ITERATIONS="$2";      shift 2 ;;
    --iterations=*) MAX_ITERATIONS="${1#*=}"; shift   ;;
    --model)       MODEL="$2";              shift 2 ;;
    --model=*)     MODEL="${1#*=}";         shift   ;;
    *)             shift ;;
  esac
done

if [[ -z "$MILESTONE" ]]; then
  echo "Error: --milestone <name> is required."
  echo "Usage: ./scripts/ralph.sh --milestone <name> [--iterations <n>]"
  exit 1
fi

# ── Preflight checks ────────────────────────────────────────────

if ! command -v gh &> /dev/null; then
  echo "Error: gh CLI not found. Install it: https://cli.github.com"
  exit 1
fi

if ! gh repo view --json name &> /dev/null; then
  echo "Error: Not in a GitHub repository or not authenticated with gh."
  exit 1
fi

# ── Create labels (idempotent) ───────────────────────────────────

echo "Ensuring Ralph labels exist..."
gh label create "ralph:todo"        --color "5319E7" --description "Story not started"     --force 2>/dev/null || true
gh label create "ralph:in-progress" --color "FBCA04" --description "Agent working on story" --force 2>/dev/null || true
gh label create "ralph:done"        --color "0E8A16" --description "Story completed"        --force 2>/dev/null || true
gh label create "ralph:failed"      --color "D93F0B" --description "Story failed"           --force 2>/dev/null || true

# ── Verify milestone exists ──────────────────────────────────────

MILESTONE_COUNT=$(gh api repos/{owner}/{repo}/milestones \
  --jq "[.[] | select(.title == \"$MILESTONE\")] | length" 2>/dev/null || echo "0")

if [[ "$MILESTONE_COUNT" -eq 0 ]]; then
  echo "Error: Milestone '$MILESTONE' not found. Run /ralph-github first to create it."
  exit 1
fi

# ── Set up branch ────────────────────────────────────────────────
# Branch name derived from milestone: "My Feature" → "ralph/my-feature"

BRANCH="ralph/$(echo "$MILESTONE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
CURRENT_BRANCH=$(git branch --show-current)

if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Checking out existing branch: $BRANCH"
    git checkout "$BRANCH"
  else
    echo "Creating new branch: $BRANCH"
    git checkout -b "$BRANCH" main
  fi
fi

# ── Finalize: push, create PR, switch back to main ──────────────

finalize() {
  local STATUS="$1"  # "complete" or "max-iterations"

  echo ""
  echo "---------------------------------------------------------------"

  # Clean up progress file — it's in the branch history but doesn't need to persist
  if [[ -f "$PROGRESS_FILE" ]]; then
    git rm "$PROGRESS_FILE" --quiet 2>/dev/null || true
    git commit -m "chore: remove progress.txt after Ralph run" --quiet 2>/dev/null || true
  fi

  echo "Pushing branch $BRANCH to origin..."
  git push -u origin "$BRANCH"

  # Set PR title based on status
  local PR_TITLE="Ralph: $MILESTONE"
  local PR_DRAFT=""
  if [[ "$STATUS" == "max-iterations" ]]; then
    PR_TITLE="WIP: Ralph: $MILESTONE"
    PR_DRAFT="--draft"
  fi

  # Fetch milestone description for PR body
  local MILESTONE_DESC
  MILESTONE_DESC=$(gh api repos/{owner}/{repo}/milestones \
    --jq ".[] | select(.title == \"$MILESTONE\") | .description" 2>/dev/null || true)

  local PR_BODY
  PR_BODY=$(cat <<PRBODY
## Milestone: $MILESTONE

${MILESTONE_DESC:-_No milestone description._}

## Status: $STATUS
PRBODY
)

  # Create PR if one doesn't already exist for this branch
  EXISTING_PR=$(gh pr list --head "$BRANCH" --state all --json number --jq '.[0].number' 2>/dev/null || true)
  if [[ -n "$EXISTING_PR" ]]; then
    echo "PR #$EXISTING_PR already exists for $BRANCH"
    gh pr edit "$EXISTING_PR" --title "$PR_TITLE" --body "$PR_BODY" 2>/dev/null || true
    if [[ "$STATUS" == "complete" ]]; then
      gh pr ready "$EXISTING_PR" 2>/dev/null || true
    fi
    PR_URL=$(gh pr view "$EXISTING_PR" --json url --jq '.url')
  else
    echo "Creating pull request..."
    PR_URL=$(gh pr create \
      --title "$PR_TITLE" \
      --body "$PR_BODY" \
      --head "$BRANCH" $PR_DRAFT 2>&1)
  fi

  echo "Switching back to main..."
  git checkout main

  echo ""
  echo "==============================================================="
  echo "  Ralph finished ($STATUS)"
  echo "  Branch: $BRANCH"
  echo "  PR:     $PR_URL"
  echo "==============================================================="
}

# ── Initialize progress file ────────────────────────────────────

if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log"    > "$PROGRESS_FILE"
  echo "Milestone: $MILESTONE"  >> "$PROGRESS_FILE"
  echo "Started: $(date)"       >> "$PROGRESS_FILE"
  echo "---"                    >> "$PROGRESS_FILE"
fi

# ── Report milestone issues ───────────────────────────────────────

echo ""
echo "Milestone: $MILESTONE"
echo "---------------------------------------------------------------"

TODO_ISSUES=$(gh issue list --milestone "$MILESTONE" --label "ralph:todo" --json number,title --jq '.[] | "  [ ] #\(.number) \(.title)"' 2>/dev/null || true)
DONE_ISSUES=$(gh issue list --milestone "$MILESTONE" --label "ralph:done" --json number,title --jq '.[] | "  [x] #\(.number) \(.title)"' 2>/dev/null || true)
IN_PROGRESS_ISSUES=$(gh issue list --milestone "$MILESTONE" --label "ralph:in-progress" --json number,title --jq '.[] | "  [~] #\(.number) \(.title)"' 2>/dev/null || true)
FAILED_ISSUES=$(gh issue list --milestone "$MILESTONE" --label "ralph:failed" --json number,title --jq '.[] | "  [!] #\(.number) \(.title)"' 2>/dev/null || true)

TODO_COUNT=$(echo "$TODO_ISSUES" | grep -c '#' 2>/dev/null || true)
DONE_COUNT=$(echo "$DONE_ISSUES" | grep -c '#' 2>/dev/null || true)
IN_PROGRESS_COUNT=$(echo "$IN_PROGRESS_ISSUES" | grep -c '#' 2>/dev/null || true)
FAILED_COUNT=$(echo "$FAILED_ISSUES" | grep -c '#' 2>/dev/null || true)
TOTAL=$((TODO_COUNT + DONE_COUNT + IN_PROGRESS_COUNT + FAILED_COUNT))

[[ -n "$DONE_ISSUES" ]]        && echo "$DONE_ISSUES"
[[ -n "$IN_PROGRESS_ISSUES" ]] && echo "$IN_PROGRESS_ISSUES"
[[ -n "$TODO_ISSUES" ]]        && echo "$TODO_ISSUES"
[[ -n "$FAILED_ISSUES" ]]      && echo "$FAILED_ISSUES"

echo "---------------------------------------------------------------"
echo "Total: $TOTAL | Done: $DONE_COUNT | Todo: $TODO_COUNT | In-progress: $IN_PROGRESS_COUNT | Failed: $FAILED_COUNT"
echo ""

# ── Main loop ────────────────────────────────────────────────────

REPO_URL=$(gh repo view --json url --jq '.url' 2>/dev/null || echo "unknown")
echo "Starting Ralph v$RALPH_VERSION - Repo: $REPO_URL - Branch: $BRANCH - Model: $MODEL - Max iterations: $MAX_ITERATIONS"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS"
  echo "==============================================================="

  # Fetch all ralph:todo issues in this milestone
  $VERBOSE && echo "  Querying: gh issue list --milestone '$MILESTONE' --label 'ralph:todo'"
  TODO_JSON=$(gh issue list \
    --milestone "$MILESTONE" \
    --label "ralph:todo" \
    --json number,title,body \
    2>/dev/null || echo "[]")
  $VERBOSE && echo "  Result: $TODO_JSON"

  TODO_COUNT=$(echo "$TODO_JSON" | jq 'length')

  # Nothing to do — either we're done, or stuck issues need a retry
  if [[ "$TODO_COUNT" -eq 0 ]]; then
    IN_PROGRESS=$(gh issue list \
      --milestone "$MILESTONE" \
      --label "ralph:in-progress" \
      --json number --jq 'length' 2>/dev/null || echo "0")

    if [[ "$IN_PROGRESS" -gt 0 ]]; then
      echo "No ralph:todo issues, but $IN_PROGRESS still in-progress. Resetting for retry..."
      gh issue list --milestone "$MILESTONE" --label "ralph:in-progress" \
        --json number --jq '.[].number' | while read -r num; do
        gh issue edit "$num" --remove-label "ralph:in-progress" --add-label "ralph:todo" 2>/dev/null || true
      done
      continue
    fi

    echo ""
    echo "Ralph completed all tasks! No remaining ralph:todo issues."
    finalize "complete"
    exit 0
  fi

  echo "$TODO_COUNT ralph:todo issue(s) remaining — agent will choose which to work on"

  # Also fetch done issues for context
  DONE_JSON=$(gh issue list \
    --milestone "$MILESTONE" \
    --label "ralph:done" \
    --json number,title \
    2>/dev/null || echo "[]")

  # Build prompt: ralph.md instructions + all todo issues (agent picks one)
  PROMPT_FILE=$(mktemp)
  trap "rm -f '$PROMPT_FILE'" EXIT
  cat "$SCRIPT_DIR/ralph.md" > "$PROMPT_FILE"
  cat >> "$PROMPT_FILE" <<ISSUE_EOF

---

## Available Issues

**Branch:** $BRANCH
**Milestone:** $MILESTONE

### Completed Issues
$(echo "$DONE_JSON" | jq -r '.[] | "- [x] #\(.number) \(.title)"' 2>/dev/null || echo "_None yet._")

### Todo Issues (pick one)
$(echo "$TODO_JSON" | jq -r '.[] | "---\n#### #\(.number) \(.title)\n\(.body)\n"')
ISSUE_EOF

  # Spawn a fresh Claude Code instance for this issue
  $VERBOSE && echo "  Prompt: $PROMPT_FILE"
  TOOL_ARGS="--dangerously-skip-permissions --print --model $MODEL"
  $VERBOSE && echo "  Spawning: $TOOL_COMMAND $TOOL_ARGS < $PROMPT_FILE"
  OUTPUT=$($TOOL_COMMAND $TOOL_ARGS < "$PROMPT_FILE" 2>&1 | tee /dev/stderr) || true
  rm -f "$PROMPT_FILE"

  # Status summary
  REMAINING=$(gh issue list --milestone "$MILESTONE" --label "ralph:todo" --json number --jq 'length' 2>/dev/null || echo "?")
  DONE_NOW=$(gh issue list --milestone "$MILESTONE" --label "ralph:done" --json number --jq 'length' 2>/dev/null || echo "?")
  FAILED_NOW=$(gh issue list --milestone "$MILESTONE" --label "ralph:failed" --json number --jq 'length' 2>/dev/null || echo "?")
  echo "Iteration $i complete — Done: $DONE_NOW | Todo: $REMAINING | Failed: $FAILED_NOW"
  sleep 2
done

# ── Max iterations reached ───────────────────────────────────────

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS)."
finalize "max-iterations"
exit 1
