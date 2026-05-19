from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings, get_settings


LINK_STORE_PATH = Path(__file__).resolve().parents[1] / "data" / "jira_issue_links.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JiraIssueAnalysis:
    issue_key: str
    summary: str
    description: str
    labels: list[str]
    priority: str | None
    reporter: str | None
    created_at: str | None
    updated_at: str | None
    task_slug: str | None
    analysis_notes: list[str]
    validation_errors: list[str]


class JiraApiError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.jira_base_url.rstrip("/")
        self._email = settings.jira_user_email
        self._token = settings.jira_api_token

    def _auth_header(self) -> str:
        raw = f"{self._email}:{self._token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise JiraApiError(f"Jira API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise JiraApiError(f"Jira API network error: {exc}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JiraApiError(f"Jira API returned invalid JSON: {exc}") from exc

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/api/3/issue/{issue_key}")

    def search_issues(self, *, jql: str, max_results: int = 25) -> list[dict[str, Any]]:
        payload = self._request(
            "POST",
            "/rest/api/3/search/jql",
            payload={
                "jql": jql,
                "maxResults": max_results,
                "fields": [
                    "summary",
                    "description",
                    "labels",
                    "priority",
                    "reporter",
                    "created",
                    "updated",
                    "status",
                ],
            },
        )
        return [item for item in (payload.get("issues") or []) if isinstance(item, dict)]


class JiraPipelineService:
    def __init__(self, settings: Settings | None = None, link_store_path: Path = LINK_STORE_PATH) -> None:
        self._settings = settings or get_settings()
        self._link_store_path = link_store_path
        self._store_lock = threading.Lock()

    def create_client(self) -> JiraClient:
        return JiraClient(self._settings)

    def default_sync_jql(self) -> str:
        project_key = self._settings.jira_project_key.strip()
        return f'project = "{project_key}" ORDER BY updated DESC'

    def get_issue_link(self, issue_key: str) -> dict[str, Any]:
        key = issue_key.strip().upper()
        with self._store_lock:
            issue = self._read_store().get("issues", {}).get(key)
        if not issue:
            return {"issue_key": key, "exists": False}
        payload = dict(issue)
        payload["exists"] = True
        return payload

    def list_issue_links(self) -> list[dict[str, Any]]:
        with self._store_lock:
            issues = self._read_store().get("issues", {})
            values = [dict(item) for item in issues.values() if isinstance(item, dict)]
        values.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        for item in values:
            item["exists"] = True
        return values

    def sync_issues(self, *, jql: str | None = None, max_results: int = 25) -> list[dict[str, Any]]:
        client = self.create_client()
        effective_jql = (jql or "").strip() or self.default_sync_jql()
        issues = client.search_issues(jql=effective_jql, max_results=max(1, min(int(max_results), 100)))
        for issue in issues:
            analysis = self.analyze_issue(issue)
            fields = issue.get("fields") or {}
            status_name = None
            if isinstance(fields.get("status"), dict):
                status_name = fields["status"].get("name")
            self._upsert_link(
                analysis.issue_key,
                {
                    "issue_key": analysis.issue_key,
                    "state": "synced",
                    "jira_status": status_name,
                    "task_slug": analysis.task_slug,
                    "analysis": analysis.__dict__,
                    "mapping_valid": not analysis.validation_errors,
                    "updated_at": analysis.updated_at or _now(),
                    "synced_at": _now(),
                },
            )
        return self.list_issue_links()

    def enqueue_issue(self, issue_payload: dict[str, Any], *, source: str, force: bool = False) -> dict[str, Any]:
        analysis = self.analyze_issue(issue_payload)
        self._upsert_link(
            analysis.issue_key,
            {
                "issue_key": analysis.issue_key,
                "state": "planned",
                "jira_status": "Selected",
                "task_slug": analysis.task_slug,
                "analysis": analysis.__dict__,
                "mapping_valid": not analysis.validation_errors,
                "updated_at": analysis.updated_at or _now(),
                "source": source,
                "force": bool(force),
            },
        )
        return {
            "accepted": True,
            "issue_key": analysis.issue_key,
            "message": f"Issue {analysis.issue_key} captured for planning.",
            "queued": False,
            "duplicate": False,
            "pipeline_id": None,
        }

    def reset_issue_link(self, issue_key: str) -> dict[str, Any]:
        key = issue_key.strip().upper()
        with self._store_lock:
            store = self._read_store()
            issues = store.setdefault("issues", {})
            existing = issues.get(key)
            if not isinstance(existing, dict):
                payload = {"issue_key": key, "exists": False}
                return payload
            reset_payload = dict(existing)
            reset_payload["state"] = "synced"
            reset_payload["updated_at"] = _now()
            reset_payload.pop("pipeline", None)
            reset_payload.pop("pipeline_id", None)
            reset_payload.pop("source", None)
            reset_payload.pop("force", None)
            issues[key] = reset_payload
            self._write_store(store)
        reset_payload["exists"] = True
        return reset_payload

    def analyze_issue(self, issue_payload: dict[str, Any]) -> JiraIssueAnalysis:
        fields = issue_payload.get("fields") or {}
        issue_key = str(issue_payload.get("key") or "").strip().upper()
        summary = str(fields.get("summary") or "").strip()
        description = self._extract_description_text(fields.get("description"))
        labels = [str(label).strip() for label in (fields.get("labels") or []) if str(label).strip()]
        priority = ((fields.get("priority") or {}).get("name") if isinstance(fields.get("priority"), dict) else None)
        reporter = ((fields.get("reporter") or {}).get("displayName") if isinstance(fields.get("reporter"), dict) else None)
        created_at = str(fields.get("created") or "").strip() or None
        updated_at = str(fields.get("updated") or "").strip() or None

        task_slug = None
        for label in labels:
            if label.lower().startswith("ai_task:"):
                task_slug = label.split(":", 1)[1].strip()
                break

        errors: list[str] = []
        if not issue_key:
            errors.append("Issue key is missing.")
        if not summary:
            errors.append("Summary is missing.")

        return JiraIssueAnalysis(
            issue_key=issue_key,
            summary=summary,
            description=description,
            labels=labels,
            priority=priority,
            reporter=reporter,
            created_at=created_at,
            updated_at=updated_at,
            task_slug=task_slug,
            analysis_notes=[],
            validation_errors=errors,
        )

    def _extract_description_text(self, description: Any) -> str:
        if description is None:
            return ""
        if isinstance(description, str):
            return description.strip()
        if not isinstance(description, dict):
            return str(description)
        text_parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("text"), str):
                    text_parts.append(node["text"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(description)
        return "\n".join(part.strip() for part in text_parts if part and part.strip()).strip()

    def _read_store(self) -> dict[str, Any]:
        if not self._link_store_path.exists():
            return {"issues": {}}
        try:
            return json.loads(self._link_store_path.read_text(encoding="utf-8"))
        except Exception:
            return {"issues": {}}

    def _write_store(self, payload: dict[str, Any]) -> None:
        self._link_store_path.parent.mkdir(parents=True, exist_ok=True)
        self._link_store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _upsert_link(self, issue_key: str, values: dict[str, Any]) -> None:
        key = issue_key.strip().upper()
        with self._store_lock:
            store = self._read_store()
            issues = store.setdefault("issues", {})
            existing = issues.get(key, {})
            merged = {**existing, **values}
            merged["issue_key"] = key
            merged["updated_at"] = merged.get("updated_at") or _now()
            issues[key] = merged
            self._write_store(store)
