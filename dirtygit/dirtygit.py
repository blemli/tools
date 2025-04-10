#!/usr/bin/env python3

import os, click
from shell import shell
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

@click.command()
@click.argument("location", default=".")
@click.option("--behind", is_flag=True, help="Check if the repo is behind the upstream")
def dirtygit(location=".", behind=False):
    repos = []
    def scan_dirs(path):
        if os.path.exists(os.path.join(path, ".git")):
            repos.append(path)
            return
        try:
            for entry in os.scandir(path):
                if entry.is_dir():
                    scan_dirs(entry.path)
        except (PermissionError, OSError):
            pass
    scan_dirs(os.path.expanduser(location))
    def check_repo(repo):
        is_dirty = shell(f"git -C {repo} status --porcelain").output()
        is_ahead = shell(f"git -C {repo} log --oneline @{{u}}..HEAD").output()
        is_behind = False
        if behind:
            shell(f"git -C {repo} fetch")
            is_behind = shell(f"git -C {repo} log --oneline HEAD..@{{u}}").output()
        if is_dirty or is_ahead or is_behind:
            return repo
        return None
    with ThreadPoolExecutor() as executor:
        results = list(tqdm(executor.map(check_repo, repos), total=len(repos)))
    dirty_repos = [repo for repo in results if repo]
    for repo in dirty_repos:
        print(repo)
    return dirty_repos

if __name__ == "__main__":
    dirtygit()
