# Deploying the ML services separately

The four ML services answer on the same API as everything else, and they do not
behave like the rest of it. Recognising a two-hundred-page scan occupies a
worker's parsing pool for minutes; serving the dashboard is a query and a
render. Running both in one process means the second waits on the first.

So this overlay runs the API image a second time as a replica that the ingress
sends only `/api/v1/ml/` to. The image, the database and the code are the same —
what is separate is the process, its CPU and memory, how many workers it runs,
and when it restarts.

That is what independent deployment means here, and it is worth being exact
about what it does not mean: this is not a second application with a second
codebase. One implementation serves the agents and the direct callers, which is
the only way the two can be guaranteed to answer the same.

## Bringing it up

```bash
docker compose -f docker-compose.yml \
               -f deploy/profiles/ml-services/docker-compose.ml.yml up -d
```

The replica joins the `backend` network and is not published on the host. It
reads the same `.env` the `app` service does, and these four variables are its
own:

| | |
|---|---|
| `ML_UVICORN_WORKERS` | Worker processes on the replica. 4 by default |
| `ML_CPUS` / `ML_MEMORY` | What the host gives it. 4 CPUs and 4g by default |
| `ML_MAX_UPLOAD_SIZE_MB` | The largest submission one call accepts. 25 by default |
| `RATE_LIMIT_ML_PER_MINUTE` | Calls one caller may make a minute. 30 by default |

Scaling it is `docker compose up -d --scale ml-services=3`, which the console
does not have to follow.

## Routing to it

Nothing in the overlay routes anything: the replica answers every path the API
does, and it is the ingress that decides it only ever sees the ML ones. Send
`/api/v1/ml/` there and everything else to `app`.

Caddy:

```caddyfile
handle /api/v1/ml/* {
    reverse_proxy ml-services:8000
}
handle {
    reverse_proxy app:8000
}
```

nginx:

```nginx
location /api/v1/ml/ {
    proxy_pass http://ml-services:8000;
    client_max_body_size 30m;
}
location / {
    proxy_pass http://app:8000;
}
```

`client_max_body_size` above the upload ceiling is not optional on nginx: its
default is 1 MB, and a document over that is refused by the proxy before the API
ever sees it.

## What it still shares

The database, Redis and the vault are the deployment's, and that is deliberate.
The call records the replica writes are read back through the console's own
`GET /api/v1/ml/calls`, the tenant scoping is the platform's, and a
transcription runs on the organization's credential out of the same vault. A
replica with a database of its own would be a second deployment, not a scaled
service.

The replica does run the same migrations check as any other API process, so
bring it up after `migrate` has completed — the compose dependency it inherits
from `app` does that for you.
