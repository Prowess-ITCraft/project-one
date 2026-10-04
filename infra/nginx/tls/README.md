# Certificates (never committed)

Production reads its certificate from `live/project-one/fullchain.pem` and
`live/project-one/privkey.pem` here, the layout certbot uses with `--cert-name project-one`.
Everything in this folder except this file is ignored by git. See `docs/runbooks/deploy.md`.
