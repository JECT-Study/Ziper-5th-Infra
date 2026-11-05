#!/usr/bin/env python3
"""Collect selected GitHub metadata and public readiness without printing secrets."""

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request


def gh_json(path):
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, timeout=45
    )
    if result.returncode:
        return {"unavailable": True}
    return json.loads(result.stdout)


def protection(repository, branch):
    raw = gh_json(f"repos/{repository}/branches/{branch}/protection")
    if raw.get("unavailable"):
        return raw
    review = raw.get("required_pull_request_reviews", {})
    return {
        "adminBypassAllowed": not raw.get("enforce_admins", {}).get("enabled", False),
        "forcePushAllowed": raw.get("allow_force_pushes", {}).get("enabled", False),
        "deletionAllowed": raw.get("allow_deletions", {}).get("enabled", False),
        "requiredApprovals": review.get("required_approving_review_count"),
        "codeOwnerReviewRequired": review.get("require_code_owner_reviews"),
        "checks": raw.get("required_status_checks", {}).get("contexts", []),
    }


def execution(repository, run_id):
    raw = gh_json(f"repos/{repository}/actions/runs/{run_id}")
    if raw.get("unavailable"):
        return {"id": run_id, "unavailable": True}
    jobs = gh_json(f"repos/{repository}/actions/runs/{run_id}/jobs")
    result = {key: raw.get(key) for key in (
        "id", "html_url", "head_sha", "head_branch", "event", "status", "conclusion"
    )}
    result["jobs"] = [
        {"name": job["name"], "conclusion": job["conclusion"],
         "steps": [{"name": step["name"], "conclusion": step["conclusion"]}
                   for step in job.get("steps", [])]}
        for job in jobs.get("jobs", [])
    ]
    notification_jobs = [job for job in jobs.get("jobs", [])
                         if "notify" in job["name"].lower()]
    if raw.get("status") == "completed" and notification_jobs:
        # Keep only the delivery receipt, never persist the complete workflow log.
        logs = subprocess.run(
            ["gh", "run", "view", str(run_id), "--repo", repository,
             "--job", str(notification_jobs[0]["id"]), "--log"],
            capture_output=True, text=True, timeout=45,
        )
        result["discordMessageIds"] = sorted(set(re.findall(
            r"Discord message confirmed: (\d+)", logs.stdout
        ))) if logs.returncode == 0 else []
    return result


def pull_request(repository, number):
    raw = gh_json(f"repos/{repository}/pulls/{number}")
    if raw.get("unavailable"):
        return {"number": number, "unavailable": True}
    return {key: raw.get(key) for key in (
        "number", "html_url", "state", "merged", "merged_at", "merge_commit_sha"
    )}


def history_rules(repository):
    raw = gh_json(f"repos/{repository}/rules/branches/main")
    if isinstance(raw, dict):
        return raw
    details = []
    for rule_id in sorted({item["ruleset_id"] for item in raw}):
        rule = gh_json(f"repos/{repository}/rulesets/{rule_id}")
        details.append({key: rule.get(key) for key in (
            "id", "name", "enforcement", "bypass_actors", "conditions", "rules"
        )})
    return details


def production_settings(repository):
    environment = gh_json(f"repos/{repository}/environments/production")
    branches = gh_json(
        f"repos/{repository}/environments/production/deployment-branch-policies"
    )
    secrets = gh_json(f"repos/{repository}/environments/production/secrets")
    repository_secrets = gh_json(f"repos/{repository}/actions/secrets")
    return {
        "deploymentBranchPolicy": environment.get("deployment_branch_policy"),
        "branches": [{"name": item["name"], "type": item.get("type")}
                     for item in branches.get("branch_policies", [])],
        "environmentSecretNames": sorted(item["name"]
                                         for item in secrets.get("secrets", [])),
        "repositorySecretNames": sorted(item["name"]
                                        for item in repository_secrets.get("secrets", [])),
        "unavailableReads": [name for name, value in (
            ("environment", environment), ("branchPolicies", branches),
            ("environmentSecrets", secrets), ("repositorySecrets", repository_secrets)
        ) if value.get("unavailable")],
    }


def readiness():
    url = "https://api-ziper.joonamin.dev/readyz"
    result = {"url": url, "checkedAt": datetime.datetime.now(
        datetime.timezone.utc).isoformat()}
    try:
        response = urllib.request.urlopen(url, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    except (urllib.error.URLError, TimeoutError):
        return {**result, "transportError": True}
    with response:
        result.update({"status": response.code,
                       "originHeader": response.headers.get("X-Ziper-Origin"),
                       "releaseHeader": response.headers.get("X-Ziper-Release")})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-run", action="append", type=int, default=[])
    parser.add_argument("--infra-run", action="append", type=int, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    infra = "JECT-Study/Ziper-5th-Infra"
    server = "JECT-Study/Ziper-5th-Server"
    data = {
        "observedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Selected GitHub executions, branch protection and public readiness only",
        "publicReadiness": readiness(),
        "protection": {infra: {"main": protection(infra, "main")},
                       server: {branch: protection(server, branch)
                                for branch in ("develop", "main")}},
        "infraMainHistoryRulesets": history_rules(infra),
        "productionSettings": {repo: production_settings(repo)
                               for repo in (infra, server)},
        "pullRequests": [pull_request(infra, 1), pull_request(server, 13),
                         pull_request(server, 14)],
        "runs": [execution(repo, run_id)
                 for repo, ids in ((infra, args.infra_run), (server, args.server_run))
                 for run_id in ids],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence written to {args.output}")


if __name__ == "__main__":
    main()
