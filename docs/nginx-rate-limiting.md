# Nginx Rate Limiting (AI Runner Webhook)

This guide adds basic but effective rate limiting to protect the AI Runner webhook endpoint from accidental loops, Jira misconfigurations, or malicious traffic.

It is designed for Jira Cloud webhook calls and a low/medium volume pilot.

---

## Why rate limit?

Even with a shared secret header, rate limiting protects against:
- Jira automation misfires (infinite assignment loops)
- Excessive retries during outages
- Bot traffic / scans hitting the endpoint
- Accidental internal load spikes

Rate limiting is recommended as a “defence-in-depth” control.

---

## Recommended policy (pilot)

### Endpoint
- `/webhook/jira`

### Limits
- **5 requests per second** per IP (burst 20)
- This is generous for Jira Cloud which typically sends low volume webhooks.

If you want stricter limits, reduce the rate to `2r/s`.

---

## Nginx configuration (copy/paste)

Add this in a file such as:

`/etc/nginx/conf.d/moveware-ai-runner-rate-limit.conf`

### 1) Define a rate limit zone


# Rate limit zone (per client IP)
limit_req_zone $binary_remote_addr zone=jira_webhooks:10m rate=5r/s;


### 2) Apply rate limiting to the webhook location

location = /webhook/jira {
    # Rate limiting
    limit_req zone=jira_webhooks burst=20 nodelay;

    # Optional: lower timeouts for webhook calls
    proxy_connect_timeout 5s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;

    # Standard reverse proxy to FastAPI/Uvicorn
    proxy_pass http://127.0.0.1:8088;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

### 3) Optional hardening
#### A) Return 429 for rate-limited requests (default behaviour)

Nginx will automatically return 429 Too Many Requests when the limit is exceeded.

You can customise the response:

limit_req_status 429;

#### B) Limit request body size (recommended)

Jira webhook payloads are small. This prevents abuse:

client_max_body_size 256k;

#### C) IP allowlisting (optional)

If you want to lock this down further, you can restrict by IP.

Note: Jira Cloud source IPs can change and are region-dependent, so allowlisting may be more effort than it’s worth for the pilot.

Example:

location = /webhook/jira {
    allow <YOUR_OFFICE_IP>;
    deny all;
    ...
}