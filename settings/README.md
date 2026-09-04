# Settings templates

`templates/*.tmpl` are sanitized hermes `config.yaml` templates with
`${VAR}` placeholders. They replace per-machine snowflake configs: the repo
carries the shared shape, each host's deploy renders it with its own env
file (KEY=VALUE lines, e.g. from `~/.hermes/.env`).

The `compose-bundle` CI job validates every template on `dev`, `update/*`,
and `vendor/*` branches (`settings_validate.py --check-only` from the
fork-upgrader plugin): dummy-value render, YAML parse, required top-level
`model`/`providers` keys, no unresolved `${...}`. Secrets are never
committed — only variable names appear in templates and CI output.
