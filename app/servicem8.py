"""Thin client for the ServiceM8 REST API (developer.servicem8.com).

Auth: Private Application API Key sent as the `X-Api-Key` header (per spec §3).
"""

import httpx

BASE_URL = "https://api.servicem8.com/api_1.0"


class ServiceM8Error(Exception):
    pass


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def test_connection(api_key: str) -> bool:
    """Hits a cheap read-only endpoint to confirm the key is valid."""
    try:
        resp = httpx.get(f"{BASE_URL}/queue.json", headers=_headers(api_key), timeout=10)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def fetch_queues(api_key: str) -> list[dict]:
    """Returns [{"uuid": ..., "name": ...}, ...]."""
    resp = httpx.get(f"{BASE_URL}/queue.json", headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    return [{"uuid": q["uuid"], "name": q.get("name", "")} for q in resp.json()]


def fetch_jobs_in_queue(api_key: str, queue_uuid: str) -> list[dict]:
    """Returns raw Job objects (per spec §3: job number, company_uuid, description)."""
    params = {"$filter": f"queue_uuid eq '{queue_uuid}'"}
    resp = httpx.get(f"{BASE_URL}/job.json", headers=_headers(api_key), params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_staff(api_key: str) -> list[dict]:
    """Returns [{"uuid": ..., "name": ...}, ...] for active ServiceM8 staff.

    Used only to let a local Worker be optionally mapped to a ServiceM8 staff
    member for booking write-back (JobActivity appears to require staff_uuid) —
    the worker list itself stays local per spec §3.
    """
    resp = httpx.get(f"{BASE_URL}/staff.json", headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    staff = []
    for s in resp.json():
        if s.get("active") == 0:
            continue
        name = f"{s.get('first', '')} {s.get('last', '')}".strip() or s.get("uuid", "")
        staff.append({"uuid": s["uuid"], "name": name})
    return staff


def fetch_company_names(api_key: str, company_uuids: list[str]) -> dict[str, str]:
    """Batch-resolve Company uuid -> name for the given ids."""
    if not company_uuids:
        return {}
    resp = httpx.get(f"{BASE_URL}/company.json", headers=_headers(api_key), timeout=20)
    resp.raise_for_status()
    wanted = set(company_uuids)
    return {c["uuid"]: c.get("name", "") for c in resp.json() if c["uuid"] in wanted}


def fetch_activity(api_key: str, activity_uuid: str) -> dict | None:
    """Fetch a single JobActivity by uuid. Returns None if it's gone or been
    deactivated in ServiceM8 (soft-deleted / booking removed there)."""
    params = {"$filter": f"uuid eq '{activity_uuid}'"}
    resp = httpx.get(f"{BASE_URL}/jobactivity.json", headers=_headers(api_key), params=params, timeout=15)
    resp.raise_for_status()
    results = resp.json()
    if not results or results[0].get("active") == 0:
        return None
    return results[0]


def create_scheduled_activity(
    api_key: str,
    job_uuid: str,
    start: str,
    end: str,
    activity_uuid: str | None = None,
    staff_uuid: str | None = None,
) -> str:
    """Create or update a JobActivity with activity_was_scheduled=1 (spec §3 write-back).

    Returns the activity's uuid. Raises ServiceM8Error with ServiceM8's own message
    on a non-2xx response, since the generic httpx exception drops the response body.
    """
    payload = {
        "job_uuid": job_uuid,
        "start_date": start,
        "end_date": end,
        "activity_was_scheduled": 1,
    }
    if staff_uuid:
        payload["staff_uuid"] = staff_uuid

    if activity_uuid:
        resp = httpx.post(
            f"{BASE_URL}/jobactivity/{activity_uuid}.json",
            headers=_headers(api_key),
            json=payload,
            timeout=15,
        )
    else:
        resp = httpx.post(
            f"{BASE_URL}/jobactivity.json", headers=_headers(api_key), json=payload, timeout=15
        )

    if resp.status_code >= 400:
        raise ServiceM8Error(f"{resp.status_code} from ServiceM8: {resp.text}")
    return resp.headers.get("x-record-uuid", activity_uuid or "")


def set_job_queue(
    api_key: str,
    job_uuid: str,
    queue_uuid: str,
    expiry: str,
    staff_uuid: str | None = None,
) -> None:
    """Move a Job into a queue. Only the queue fields are sent, so nothing
    else on the job is touched. ServiceM8 wants a queue_expiry_date with every
    queue_uuid — without one an API-queued job also lingers in Unscheduled.
    Raises ServiceM8Error with ServiceM8's own message on a non-2xx response."""
    payload = {"queue_uuid": queue_uuid, "queue_expiry_date": expiry}
    if staff_uuid:
        payload["queue_assigned_staff_uuid"] = staff_uuid
    resp = httpx.post(f"{BASE_URL}/job/{job_uuid}.json", headers=_headers(api_key), json=payload, timeout=15)
    if resp.status_code >= 400:
        raise ServiceM8Error(f"{resp.status_code} from ServiceM8: {resp.text}")
