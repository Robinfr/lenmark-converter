Use `python3` for local Python commands.

For Docker, use Colima's socket:
`env DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"`.

Do not silently discard unsupported project data. Reject the affected file
and report the reason. Keep customer artwork and vendor binaries out of Git.
Distinguish binary/coordinate verification from acceptance by LenMark itself.
