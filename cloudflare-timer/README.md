# Dashboard timer (Cloudflare Worker)
Starts the GitHub job "Refresh dashboard" every hour. Cron trigger: `7 * * * *` (minute 7 of every hour, UTC).
Secret: `GITHUB_TOKEN` (fine-grained token, only this repo, permission Actions: Read and write). Never commit the token.
To change the schedule: Cloudflare > Workers & Pages > klenty-dashboard-timer > Settings > Trigger Events.
