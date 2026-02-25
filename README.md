# gitlab-reconciler

Simple webhook-driven microservice for reconciling GitLab groups and membership.

## Environment

- `GITLAB_URL` (e.g. `https://gitlab.example.com`)
- `GITLAB_TOKEN` (access token with API scope)
- `WEBHOOK_TOKEN` (shared secret for `Authorization: Bearer <token>` header)
- `USER_PATH` (parent path under which per-user groups are created)
- `GROUP_PATH` (parent path under which named groups are created)
- `USER_PREFIX` (prefix for per-user subgroup names, defaults to `u-`)
- `GROUP_PREFIX` (prefix for named subgroup names, defaults to `g-`)

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GITLAB_URL="https://gitlab.example.com"
export GITLAB_TOKEN="<token>"
export WEBHOOK_TOKEN="<webhook-token>"
export USER_PATH="users"
export GROUP_PATH="groups"
export USER_PREFIX="u-"
export GROUP_PREFIX="g-"

uvicorn app:app --host "" --port 8000
```

## Webhook

`POST /` (Requires `Authorization: Bearer <token>` header)

Example payload:

```json
{
  "users": ["2001", "2002"],
  "groups": {
    "g1": ["2001", "2002"]
  }
}
```

Notes:

- Access level is set to Maintainer (40).
- Send `Authorization: Bearer <WEBHOOK_TOKEN>` with the request.
- If `USER_PATH` or `GROUP_PATH` are nested (contain `/`), they must already
  exist.
- User subgroup names are created as `<USER_PREFIX><username>` (example:
  `alice` -> `u-alice`).
- Group subgroup names are created as `<GROUP_PREFIX><group_name>` (example:
  `dod` -> `g-dod`).
