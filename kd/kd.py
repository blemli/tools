#!/usr/bin/env python3
"""kd — kamal destination manager, per project.

Destinations are stored per project under ~/.config/kd/dest/ (one file per
project root, path-encoded), so `kd local` in one repo never leaks into
another. The kamal() zsh wrapper in kd.zsh routes every kamal call through
`kd run`, which injects -d, guards production, and maps the special "local"
destination to a plain docker build/run of the current project.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml
from click.shell_completion import CompletionItem

DEST_DIR = Path.home() / ".config" / "kd" / "dest"
DESTRUCTIVE = {"deploy", "redeploy", "remove", "rollback"}
DESTRUCTIVE_COMPOUND = {("app", "stop"), ("app", "remove")}
DEFAULT_LOCAL_PORT = 8080


# --- project helpers ---------------------------------------------------------

def git_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def kamal_project_root():
    root = git_root()
    if root and (root / "config" / "deploy.yml").is_file() and (root / ".kamal").is_dir():
        return root
    return None


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def discover_destinations(root):
    return sorted(f.name[len("deploy."):-len(".yml")]
                  for f in (root / "config").glob("deploy.*.yml"))


def app_port(root):
    cfg = load_yaml(root / "config" / "deploy.yml")
    return (cfg.get("proxy") or {}).get("app_port", DEFAULT_LOCAL_PORT)


def secret_keys(root):
    cfg = load_yaml(root / "config" / "deploy.yml")
    keys = (cfg.get("env") or {}).get("secret") or []
    return [k for k in keys if isinstance(k, str)]


# --- destination state -------------------------------------------------------

def dest_file(root):
    return DEST_DIR / str(root).replace("/", "%")


def get_dest(root=None):
    root = root or git_root()
    if not root:
        return None
    f = dest_file(root)
    return f.read_text().strip() if f.is_file() else None


def write_dest(root, dest):
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest_file(root).write_text(dest + "\n")


def clear_dest(root):
    dest_file(root).unlink(missing_ok=True)


def complete_dest(ctx, param, incomplete):
    root = kamal_project_root()
    names = (discover_destinations(root) if root else []) + ["local", "off"]
    return [CompletionItem(n) for n in names if n.startswith(incomplete)]


# --- cli ----------------------------------------------------------------------

class KdCLI(click.Group):
    """`kd staging` == `kd set staging` — unknown first args fall through to set."""

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return "set", self.get_command(ctx, "set"), args

    def shell_complete(self, ctx, incomplete):
        return super().shell_complete(ctx, incomplete) + complete_dest(ctx, None, incomplete)


@click.group(cls=KdCLI, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """kd — kamal destination manager (per project).

    \b
    kd                 interactive destination picker
    kd DEST            set destination (a deploy.<DEST>.yml, "local" or "off")
    kd env             print current destination
    kd run -- ARGS...  kamal wrapper (used by the kamal() shell function)
    kd open            open the site URL for the current destination
    kd getdb           pull sqlite databases from the remote destination
    """
    if ctx.invoked_subcommand is None:
        interactive_menu()


def require_project():
    root = kamal_project_root()
    if not root:
        click.echo("Not a Kamal project (no config/deploy.yml or .kamal/)")
        sys.exit(1)
    return root


def apply_dest(root, dest, dests):
    if dest == "local":
        write_dest(root, dest)
        click.echo(f"kamal destination: {dest}")
    elif dest in ("off", "clear", "none"):
        clear_dest(root)
        click.echo("kamal destination cleared")
    else:
        if not dests:
            click.echo("No destinations available (no deploy.<dest>.yml files). "
                       "Use 'local' or 'off'.")
            sys.exit(1)
        if dest not in dests:
            click.echo(f"Unknown: {dest} (available: {' '.join(dests)}, local, off)")
            sys.exit(1)
        write_dest(root, dest)
        click.echo(f"kamal destination: {dest}")


def interactive_menu():
    root = require_project()
    dests = discover_destinations(root)
    current = get_dest(root)
    click.echo(f"Current: {current}" if current else "Current: (none)")
    click.echo("")

    if not dests:
        click.echo("  No deploy.<dest>.yml files found.")
        click.echo("  deploy.yml is used directly (no -d flag needed).")
        click.echo("")
        click.echo("  1) local")
        click.echo("  2) off (clear)")
        choice = input("> ").strip()
        if choice in ("1", "l"):
            dest = "local"
        elif choice in ("2", "o", "off"):
            dest = "off"
        else:
            click.echo("Invalid choice.")
            sys.exit(1)
    else:
        for i, d in enumerate(dests, 1):
            click.echo(f"  {i}) {d}")
        local_i, off_i = len(dests) + 1, len(dests) + 2
        click.echo(f"  {local_i}) local")
        click.echo(f"  {off_i}) off (clear)")
        choice = input("> ").strip()
        if choice == "l":
            dest = "local"
        elif choice in ("o", "off"):
            dest = "off"
        elif choice.isdigit():
            n = int(choice)
            if n == local_i:
                dest = "local"
            elif n == off_i:
                dest = "off"
            elif 1 <= n <= len(dests):
                dest = dests[n - 1]
            else:
                click.echo("Invalid choice.")
                sys.exit(1)
        else:
            # first-letter match against destinations
            dest = next((d for d in dests if d.startswith(choice)), None)
            if not dest:
                click.echo("Invalid choice.")
                sys.exit(1)

    apply_dest(root, dest, dests)


@cli.command("set")
@click.argument("dest", shell_complete=complete_dest)
def set_cmd(dest):
    """Set the destination for this project."""
    root = require_project()
    apply_dest(root, dest, discover_destinations(root))


@cli.command()
def env():
    """Print the current destination (kdenv)."""
    dest = get_dest()
    if dest:
        click.echo(dest)
    else:
        click.echo("No destination set (use kd)", err=True)
        sys.exit(1)


# --- kamal wrapper -------------------------------------------------------------

@cli.command(context_settings=dict(ignore_unknown_options=True, help_option_names=[]))
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def run(args):
    """Kamal wrapper: inject -d, guard production, route 'local' to docker."""
    args = list(args)
    dest = get_dest()

    if dest == "local":
        sys.exit(local_mode(args))

    has_d = any(a == "-d" or a.startswith("--destination") for a in args)
    root = kamal_project_root()
    dests = discover_destinations(root) if root else []

    destructive = bool(args) and (args[0] in DESTRUCTIVE
                                  or tuple(args[:2]) in DESTRUCTIVE_COMPOUND)
    if dest == "production" and not has_d and destructive:
        shown = "kamal " + " ".join(args) + (" -d production" if dests else "")
        click.echo(click.style("PRODUCTION", fg="red") + f": {shown}")
        if input("Continue? [y/N] ").strip().lower() != "y":
            click.echo("Aborted.")
            sys.exit(1)

    cmd = ["kamal"] + args
    if dest and not has_d and dest in dests:
        cmd += ["-d", dest]
    try:
        os.execvp("kamal", cmd)
    except FileNotFoundError:
        click.echo("kamal not found in PATH", err=True)
        sys.exit(127)


# --- local docker mode ----------------------------------------------------------

def local_mode(args):
    root = git_root()
    if not root:
        click.echo("Not in a git repo")
        return 1
    name = root.name
    container = f"{name}-local"
    image = f"{name}:local"
    port = app_port(root)
    sub, rest = (args[0], args[1:]) if args else ("", [])

    if sub in ("deploy", "redeploy"):
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)

        click.echo(f"Building image {image}...")
        if subprocess.run(["docker", "build", "-t", image, str(root)]).returncode:
            return 1

        env_args = []
        if name == "audiobeam":
            click.echo("Fetching encryption key from 1Password...")
            r = subprocess.run(
                ["op", "read", "op://PROBLEMLI/audiobeam .env.staging.encrypted/Password"],
                capture_output=True, text=True)
            if r.returncode:
                click.echo("Failed to fetch key from 1Password")
                return 1
            env_args += ["-e", "APP_ENV=staging",
                         "-e", f"LARAVEL_ENV_ENCRYPTION_KEY={r.stdout.strip()}"]
        else:
            keys = secret_keys(root)
            if keys:
                click.echo(f"Fetching secrets ({', '.join(keys)})...")
                r = subprocess.run(["kamal", "secrets", "print"],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    found = dict(line.split("=", 1)
                                 for line in r.stdout.splitlines() if "=" in line)
                    for k in keys:
                        if k in found:
                            env_args += ["-e", f"{k}={found[k]}"]
                        else:
                            click.echo(f"  ! {k} not found in kamal secrets")
                else:
                    click.echo("  ! kamal secrets print failed — starting without secrets")

        click.echo(f"Starting {container} on port {port}...")
        if subprocess.run(["docker", "run", "-d",
                           "--name", container,
                           "-p", f"{port}:{port}",
                           "-v", f"{name}_local_db:/data",
                           *env_args, image]).returncode:
            return 1
        click.echo(f"→ http://localhost:{port}")
        subprocess.run(["open", f"http://localhost:{port}"])
        return 0

    if sub == "ssh":
        return subprocess.run(["docker", "exec", "-it", container, "sh"]).returncode

    if sub == "tinker":
        return subprocess.run(["docker", "exec", "-it", container,
                               "php", "artisan", "tinker"]).returncode

    if sub == "app":
        app_sub, app_args = (rest[0], rest[1:]) if rest else ("", [])
        if app_sub == "logs":
            flags = ["-f"] if "--follow" in app_args else []
            return subprocess.run(["docker", "logs", *flags, container]).returncode
        if app_sub == "exec":
            # strip kamal-specific flags, translate -i to interactive
            interactive, cmd = False, []
            for a in app_args:
                if a in ("-i", "--interactive"):
                    interactive = True
                elif a in ("--reuse", "--quiet", "-q"):
                    pass  # kamal-only flags
                else:
                    cmd.append(a)
            it = ["-it"] if interactive else []
            return subprocess.run(["docker", "exec", *it, container, *cmd]).returncode
        if app_sub == "version":
            return subprocess.run(["docker", "exec", container,
                                   "jq", "-r", ".version", "composer.json"]).returncode
        click.echo(f"local: kamal app {app_sub} not mapped")
        return 1

    if sub == "remove":
        subprocess.run(["docker", "rm", "-f", container])
        click.echo(f"Container removed. Volume {name}_local_db kept.")
        click.echo(f"To also remove data: docker volume rm {name}_local_db")
        return 0

    click.echo(f"local: kamal {sub} not mapped")
    click.echo("Supported: deploy, redeploy, ssh, tinker, app logs/exec/version, remove")
    return 1


# --- kamo / getdb ----------------------------------------------------------------

@cli.command("open")
@click.option("-d", "--dest", "dest_opt", help="override destination")
@click.argument("dest_arg", required=False, shell_complete=complete_dest)
def open_cmd(dest_opt, dest_arg):
    """Open the site URL for the current destination (kamo)."""
    dest = dest_opt or dest_arg or get_dest()

    if not dest:
        root = git_root()
        if not root:
            click.echo("Not in a git repo")
            sys.exit(1)
        # bare-deploy.yml kamal project: no destination means deploy.yml itself
        host = (load_yaml(root / "config" / "deploy.yml").get("proxy") or {}).get("host")
        url = f"https://{host}" if host else f"https://{root.name}.test"
    elif dest == "local":
        root = git_root()
        port = app_port(root) if root else DEFAULT_LOCAL_PORT
        url = f"http://localhost:{port}"
    else:
        root = require_project()
        dest_yml = root / "config" / f"deploy.{dest}.yml"
        host = None
        if dest_yml.is_file():
            host = (load_yaml(dest_yml).get("proxy") or {}).get("host")
            if not host:
                # kamal merges destination over base config — host may live in deploy.yml
                host = (load_yaml(root / "config" / "deploy.yml").get("proxy") or {}).get("host")
        if not host:
            click.echo(f"No host found for destination: {dest}", err=True)
            sys.exit(1)
        url = f"https://{host}"

    click.echo(f"Opening {url}")
    subprocess.run(["open", url])


@cli.command()
@click.argument("dest", required=False, shell_complete=complete_dest)
@click.option("--db", "dbs", multiple=True,
              help="db filename in /data (default: database.sqlite, ceebo.sqlite)")
def getdb(dest, dbs):
    """Pull sqlite databases from the remote destination via ssh."""
    root = git_root()
    if not root:
        click.echo("Not in a git repo")
        sys.exit(1)
    dest = dest or get_dest()
    if not dest:
        click.echo("No destination set (use kd)", err=True)
        sys.exit(1)

    name = root.name
    remote = f"{name}-{dest}"
    db_dir = root / "database"

    for db in dbs or ("database.sqlite", "ceebo.sqlite"):
        target = db_dir / db
        if target.is_file():
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        click.echo(f"Dumping {db} from {remote}...")
        ok = (subprocess.run(["ssh", remote,
                              f"sqlite3 /data/{db} '.backup /tmp/{db}'"]).returncode == 0
              and subprocess.run(["scp", f"{remote}:/tmp/{db}",
                                  str(target)]).returncode == 0)
        click.echo(f"  ✓ {db}" if ok else f"  ✗ {db} failed")

    # kitty terminal notification
    print(f"\x1b]99;i=getdb;d=0;Database copied from {name} {dest}\x1b\\", end="")


if __name__ == "__main__":
    # invoked through the shim as kd.py — pin the name so --help and the
    # _KD_COMPLETE completion hook see "kd"
    cli(prog_name="kd")
