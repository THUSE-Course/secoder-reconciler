import os
from typing import Optional
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException, Header

GITLAB_URL = os.getenv("GITLAB_URL")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")
USER_PATH = os.getenv("USER_PATH")
GROUP_PATH = os.getenv("GROUP_PATH")

if not GITLAB_URL or not GITLAB_TOKEN:
    # Defer hard failure until first request to make local dev easier.
    pass

API_PREFIX = "/api/v4"
TIMEOUT = 10
MAINTAINER_ACCESS = 40

app = FastAPI(title="gitlab-reconciler", version="0.1.0")


def _headers():
    if not GITLAB_TOKEN:
        raise HTTPException(
            status_code=500, detail="Missing GITLAB_TOKEN env var"
        )
    return {"PRIVATE-TOKEN": GITLAB_TOKEN}


def _base_url():
    if not GITLAB_URL:
        raise HTTPException(
            status_code=500, detail="Missing GITLAB_URL env var"
        )
    return GITLAB_URL.rstrip("/") + API_PREFIX


def get_user_id(username: str) -> int:
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    url = f"{_base_url()}/users"
    resp = requests.get(
        url, headers=_headers(), params={"username": username}, timeout=TIMEOUT
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = resp.json()
    if not data:
        raise HTTPException(
            status_code=404, detail=f"User not found: {username}"
        )
    return data[0]["id"]


def get_group_id(full_path: str) -> Optional[int]:
    encoded = quote(full_path, safe="")
    get_url = f"{_base_url()}/groups/{encoded}"
    resp = requests.get(get_url, headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 200:
        return resp.json()["id"]
    if resp.status_code == 404:
        return None
    raise HTTPException(status_code=resp.status_code, detail=resp.text)


def create_group(name: str, path: str, parent_id: Optional[int]) -> int:
    create_url = f"{_base_url()}/groups"
    payload = {"name": name, "path": path}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    resp = requests.post(
        create_url, headers=_headers(), json=payload, timeout=TIMEOUT
    )
    if resp.status_code not in (201, 200):
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()["id"]


def get_or_create_group(
    full_path: str, name: str, path: str, parent_id: Optional[int]
) -> int:
    group_id = get_group_id(full_path)
    if group_id is not None:
        return group_id
    return create_group(name, path, parent_id)


def name_from_path(path: str) -> str:
    return path.rstrip("/").split("/")[-1]


def add_user_to_group(group_id: int, user_id: int) -> str:
    url = f"{_base_url()}/groups/{group_id}/members"
    payload = {"user_id": user_id, "access_level": MAINTAINER_ACCESS}
    resp = requests.post(url, headers=_headers(), json=payload, timeout=TIMEOUT)
    if resp.status_code in (201, 200):
        return "added"
    if resp.status_code == 409:
        # Already a member; ensure access level is at least maintainer.
        update_url = f"{_base_url()}/groups/{group_id}/members/{user_id}"
        update_payload = {"access_level": MAINTAINER_ACCESS}
        update_resp = requests.put(
            update_url, headers=_headers(), json=update_payload, timeout=TIMEOUT
        )
        if update_resp.status_code in (200, 201):
            return "updated"
        raise HTTPException(
            status_code=update_resp.status_code, detail=update_resp.text
        )

    raise HTTPException(status_code=resp.status_code, detail=resp.text)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/")
def webhook(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    if not WEBHOOK_TOKEN:
        raise HTTPException(
            status_code=500, detail="Missing WEBHOOK_TOKEN env var"
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not USER_PATH or not GROUP_PATH:
        raise HTTPException(
            status_code=500, detail="Missing USER_PATH or GROUP_PATH env var"
        )
    users = payload.get("users", [])
    groups = payload.get("groups", {})
    if not isinstance(users, list) or not isinstance(groups, dict):
        raise HTTPException(status_code=400, detail="Invalid payload shape")
    results = []
    if "/" in USER_PATH.strip("/"):
        user_parent_id = get_group_id(USER_PATH)
        if user_parent_id is None:
            raise HTTPException(
                status_code=500,
                detail="USER_PATH must exist when using nested paths",
            )
    else:
        user_parent_id = get_or_create_group(
            USER_PATH, name_from_path(USER_PATH), USER_PATH, None
        )

    if "/" in GROUP_PATH.strip("/"):
        group_parent_id = get_group_id(GROUP_PATH)
        if group_parent_id is None:
            raise HTTPException(
                status_code=500,
                detail="GROUP_PATH must exist when using nested paths",
            )
    else:
        group_parent_id = get_or_create_group(
            GROUP_PATH, name_from_path(GROUP_PATH), GROUP_PATH, None
        )

    for user_id_str in users:
        user_id = get_user_id(user_id_str)
        user_group_full_path = f"{USER_PATH}/{user_id_str}"
        user_group_id = get_or_create_group(
            user_group_full_path, user_id_str, user_id_str, user_parent_id
        )
        action = add_user_to_group(user_group_id, user_id)
        results.append(
            {
                "group": user_group_full_path,
                "user": user_id,
                "action": action,
            }
        )

    for group_name, user_ids in groups.items():
        group_full_path = f"{GROUP_PATH}/{group_name}"
        group_id = get_or_create_group(
            group_full_path, group_name, group_name, group_parent_id
        )
        for user_id_str in user_ids:
            user_id = get_user_id(user_id_str)
            action = add_user_to_group(group_id, user_id)
            results.append(
                {
                    "group": group_full_path,
                    "user": user_id,
                    "action": action,
                }
            )
    return {"status": "ok", "results": results}
